"""Residents: a user with role=resident, linked to a flat by a `residents` row.

Creating a resident creates both the login (user) and the flat link in one transaction.
"""

import uuid

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager

from app.core.security import hash_password
from app.models import Flat, Resident, User
from app.models.enums import ResidentType, UserRole
from app.schemas.user import ResidentCreate, ResidentUpdate
from app.services import audit
from app.services.auth import revoke_all_sessions
from app.services.db_helpers import get_in_society, integrity_guard
from app.services.errors import NotFoundError
from app.services.pagination import PageRequest, PageResult, paginate

# Fields of ResidentUpdate that live on the user, not on the flat link.
_USER_FIELDS = {"full_name", "phone", "is_active"}


def _with_user_and_flat() -> Select[Resident]:
    return (
        select(Resident)
        .join(Resident.user)
        .join(Resident.flat)
        .options(contains_eager(Resident.user), contains_eager(Resident.flat))
    )


async def list_residents(
    db: AsyncSession,
    actor: User,
    page: PageRequest,
    *,
    flat_id: uuid.UUID | None = None,
    block: str | None = None,
    resident_type: ResidentType | None = None,
    is_active: bool | None = None,
    q: str | None = None,
) -> PageResult[Resident]:
    statement = (
        _with_user_and_flat()
        .where(Flat.society_id == actor.society_id)
        .order_by(Flat.block, Flat.number, User.full_name)
    )
    if flat_id:
        statement = statement.where(Resident.flat_id == flat_id)
    if block:
        statement = statement.where(Flat.block == block.upper())
    if resident_type:
        statement = statement.where(Resident.resident_type == resident_type)
    if is_active is not None:
        statement = statement.where(User.is_active == is_active)
    if q:
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(User.full_name.ilike(pattern), User.email.ilike(pattern), User.phone.ilike(pattern))
        )
    return await paginate(db, statement, page)


async def get_resident(db: AsyncSession, actor: User, resident_id: uuid.UUID) -> Resident:
    resident = await db.scalar(
        _with_user_and_flat().where(Resident.id == resident_id, Flat.society_id == actor.society_id)
    )
    if resident is None:
        raise NotFoundError("Resident not found")
    return resident


async def _make_sole_primary_contact(db: AsyncSession, resident: Resident) -> None:
    """A flat has at most one primary contact: the first person asked to approve visitors."""
    await db.execute(
        update(Resident)
        .where(Resident.flat_id == resident.flat_id, Resident.id != resident.id)
        .values(is_primary_contact=False)
    )


async def create_resident(db: AsyncSession, actor: User, data: ResidentCreate) -> Resident:
    flat = await get_in_society(db, Flat, data.flat_id, actor.society_id)
    user = User(
        society_id=actor.society_id,
        email=data.email,
        full_name=data.full_name,
        phone=data.phone,
        role=UserRole.RESIDENT,
        password_hash=hash_password(data.password),
    )
    resident = Resident(
        user=user,
        flat=flat,
        resident_type=data.resident_type,
        is_primary_contact=data.is_primary_contact,
    )
    async with integrity_guard(db, f"A user with email {data.email} already exists"):
        db.add(resident)
    if resident.is_primary_contact:
        await _make_sole_primary_contact(db, resident)
    audit.record(
        db,
        actor,
        "resident.create",
        resident.id,
        audit.snapshot(data.model_dump(exclude={"password"})),
    )
    await db.commit()
    return resident


async def update_resident(
    db: AsyncSession, actor: User, resident_id: uuid.UUID, data: ResidentUpdate
) -> Resident:
    resident = await get_resident(db, actor, resident_id)
    updates = data.changes()
    changes = audit.apply_changes(
        resident.user, {k: v for k, v in updates.items() if k in _USER_FIELDS}
    )
    changes |= audit.apply_changes(
        resident, {k: v for k, v in updates.items() if k not in _USER_FIELDS}
    )
    if changes.get("is_primary_contact") == [False, True]:
        await _make_sole_primary_contact(db, resident)
    if changes.get("is_active") == [True, False]:
        await revoke_all_sessions(db, resident.user_id)
    if changes:
        audit.record(db, actor, "resident.update", resident.id, changes)
    await db.commit()
    return resident


async def remove_resident(db: AsyncSession, actor: User, resident_id: uuid.UUID) -> None:
    """Remove the person from the flat. If they belong to no other flat, their login is
    deactivated (not deleted, so their past approvals stay attributed to them)."""
    resident = await get_resident(db, actor, resident_id)
    user = resident.user
    await db.delete(resident)
    await db.flush()

    other_flats = await db.scalar(
        select(func.count()).select_from(Resident).where(Resident.user_id == user.id)
    )
    if not other_flats:
        user.is_active = False
        await revoke_all_sessions(db, user.id)
    audit.record(
        db,
        actor,
        "resident.remove",
        resident_id,
        {"user_id": str(user.id), "flat": resident.flat.label, "deactivated": not other_flats},
    )
    await db.commit()
