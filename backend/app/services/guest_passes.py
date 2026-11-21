"""Guest passes: a resident pre-approves a guest, by plate or by a one-time code.

- **Plate pass:** the entry camera reads the plate → the gate engine admits the car with
  no approval round-trip (`admit_with_pass`), counting one use.
- **Code pass:** the guest shows an 8-character code; the guard types it
  (`redeem_code`). Codes use an alphabet without look-alikes (no I/L/O/0/1) and are stored
  only as an HMAC with the server secret: a database leak doesn't reveal working codes,
  and short codes can't be brute-forced offline.
- A use is counted with one atomic UPDATE ("add 1 if still under the limit"), so two cars
  arriving together can't both use the last entry.
"""

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import GuestPass, User, Visit
from app.models.enums import UserRole, VisitStatus, VisitTrigger
from app.schemas.guest_pass import GuestPassCreate
from app.services.errors import ConflictError, InvalidInputError, NotFoundError
from app.services.pagination import PageRequest, PageResult, paginate
from app.services.plates import normalize_typed_plate
from app.services.visitors import resident_flat_ids, utcnow
from app.services.visits import start_visit, transition_visit

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def hash_code(settings: Settings, code: str) -> str:
    key = settings.jwt_secret_key.encode()
    return hmac.new(key, code.strip().upper().encode(), hashlib.sha256).hexdigest()


async def _resident_flat(db: AsyncSession, resident: User, flat_id: uuid.UUID | None) -> uuid.UUID:
    flats = await resident_flat_ids(db, resident)
    if flat_id is not None:
        if flat_id not in flats:
            raise NotFoundError("Flat not found")
        return flat_id
    if len(flats) != 1:
        raise InvalidInputError("You're linked to several flats: say which one (flat_id)")
    return flats[0]


async def create_pass(
    db: AsyncSession, settings: Settings, resident: User, data: GuestPassCreate
) -> tuple[GuestPass, str | None]:
    flat_id = await _resident_flat(db, resident, data.flat_id)
    if data.valid_until <= utcnow():
        raise InvalidInputError("valid_until is already in the past")
    code = new_code() if data.with_code else None
    guest_pass = GuestPass(
        society_id=resident.society_id,
        flat_id=flat_id,
        created_by_id=resident.id,
        guest_name=data.guest_name,
        guest_phone=data.guest_phone,
        category=data.category,
        plate_normalized=normalize_typed_plate(data.plate) if data.plate else None,
        code_hash=hash_code(settings, code) if code else None,
        valid_from=data.valid_from,
        valid_until=data.valid_until,
        max_uses=data.max_uses,
        use_count=0,
    )
    db.add(guest_pass)
    await db.commit()
    return guest_pass, code


async def list_passes(
    db: AsyncSession, user: User, page: PageRequest, *, active: bool | None = None
) -> PageResult[GuestPass]:
    statement = (
        select(GuestPass)
        .where(GuestPass.society_id == user.society_id)
        .order_by(GuestPass.created_at.desc())
    )
    if user.role is UserRole.RESIDENT:
        statement = statement.where(GuestPass.flat_id.in_(await resident_flat_ids(db, user)))
    if active:
        now = utcnow()
        statement = statement.where(*_valid_at(now))
    return await paginate(db, statement, page)


async def revoke_pass(db: AsyncSession, resident: User, pass_id: uuid.UUID) -> GuestPass:
    guest_pass = await db.get(GuestPass, pass_id)
    if guest_pass is None or guest_pass.flat_id not in await resident_flat_ids(db, resident):
        raise NotFoundError("Guest pass not found")
    if guest_pass.revoked_at is None:
        guest_pass.revoked_at = utcnow()
        await db.commit()
    return guest_pass


def _valid_at(at: datetime) -> tuple[ColumnElement[bool], ...]:
    return (
        GuestPass.revoked_at.is_(None),
        GuestPass.valid_from <= at,
        GuestPass.valid_until > at,
        GuestPass.use_count < GuestPass.max_uses,
    )


async def plate_passes(
    db: AsyncSession, society_id: uuid.UUID, plate: str, at: datetime, max_distance: int
) -> list[GuestPass]:
    """Plate passes usable at `at` whose plate could be within `max_distance` edits."""
    length = func.length(GuestPass.plate_normalized)
    rows = await db.scalars(
        select(GuestPass)
        .where(
            GuestPass.society_id == society_id,
            GuestPass.plate_normalized.is_not(None),
            length.between(len(plate) - max_distance, len(plate) + max_distance),
            *_valid_at(at),
        )
        .order_by(GuestPass.created_at)
    )
    return list(rows)


async def _use_once(db: AsyncSession, guest_pass: GuestPass, at: datetime) -> None:
    used = await db.scalar(
        update(GuestPass)
        .where(GuestPass.id == guest_pass.id, *_valid_at(at))
        .values(use_count=GuestPass.use_count + 1)
        .returning(GuestPass.id)
    )
    if used is None:
        raise ConflictError("This guest pass is used up, revoked or not valid right now")
    await db.refresh(guest_pass)


async def admit_with_pass(
    db: AsyncSession,
    settings: Settings,
    guest_pass: GuestPass,
    *,
    at: datetime,
    plate: str | None,
    gate_event_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> Visit:
    """Count one use, create an already-approved visit, and move it INSIDE."""
    await _use_once(db, guest_pass, at)
    visit = await start_visit(
        db,
        society_id=guest_pass.society_id,
        flat_id=guest_pass.flat_id,
        category=guest_pass.category,
        status=VisitStatus.APPROVED,
        at=at,
        note=f"guest pass for {guest_pass.guest_name}",
        plate=plate or guest_pass.plate_normalized,
        guest_pass_id=guest_pass.id,
        purpose=f"Guest pass: {guest_pass.guest_name}",
        registered_by_id=actor_id,
        approved_by_id=guest_pass.created_by_id,
    )
    await transition_visit(
        db,
        settings,
        visit,
        VisitTrigger.ENTER,
        at=at,
        actor_id=actor_id,
        gate_event_id=gate_event_id,
        note="admitted with guest pass",
    )
    return visit


async def redeem_code(
    db: AsyncSession, settings: Settings, guard: User, code: str, plate: str | None
) -> Visit:
    now = utcnow()
    guest_pass = await db.scalar(
        select(GuestPass).where(
            GuestPass.society_id == guard.society_id,
            GuestPass.code_hash == hash_code(settings, code),
        )
    )
    if guest_pass is None:
        raise NotFoundError("No guest pass with this code")
    visit = await admit_with_pass(
        db,
        settings,
        guest_pass,
        at=now,
        plate=normalize_typed_plate(plate) if plate else None,
        actor_id=guard.id,
    )
    await db.commit()
    return visit
