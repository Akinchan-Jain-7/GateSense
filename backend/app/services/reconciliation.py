"""Nightly reconciliation: find gate records that don't add up, and flag them for the admin.

- **exit without entry**: a resident's car left but was never seen coming in (missed read
  at the entry camera, or a tailgate).
- **entry never closed**: a resident's car was seen coming in, then coming in *again*,
  with no exit in between: the exit was missed.
- **visit not closed**: a visitor still "inside" a day after the time limit: probably left
  unseen; the guard or admin should close it.

A resident car that entered and is simply parked at home is normal, so a single open entry
is never flagged. Flags are unique per (kind, record): the job can run any number of times.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import Settings
from app.models import GateEvent, ReconciliationFlag, User, Visit
from app.models.enums import LaneDirection, MatchResult, ReconciliationKind
from app.services.db_helpers import get_in_society
from app.services.errors import ConflictError
from app.services.pagination import PageRequest, PageResult, paginate
from app.services.visit_state import INSIDE_STATUSES

# Give a just-arrived exit a moment: its entry read may still be in an offline camera's buffer.
GRACE = timedelta(hours=1)


async def _flag(
    db: AsyncSession,
    *,
    society_id: uuid.UUID,
    kind: ReconciliationKind,
    details: str,
    gate_event_id: uuid.UUID | None = None,
    visit_id: uuid.UUID | None = None,
) -> bool:
    subject = gate_event_id or visit_id
    assert subject is not None  # noqa: S101 - every finding is about an event or a visit
    new = await db.scalar(
        insert(ReconciliationFlag)
        .values(
            id=uuid.uuid4(),
            society_id=society_id,
            kind=kind,
            subject_id=subject,
            gate_event_id=gate_event_id,
            visit_id=visit_id,
            details=details,
        )
        .on_conflict_do_nothing(constraint="one_flag_per_finding")
        .returning(ReconciliationFlag.id)
    )
    return new is not None


async def reconcile(
    db: AsyncSession, settings: Settings, now: datetime | None = None
) -> dict[str, int]:
    now = now or datetime.now(UTC)
    counts = {kind.value: 0 for kind in ReconciliationKind}

    entry = aliased(GateEvent)
    exits_alone = await db.scalars(
        select(GateEvent).where(
            GateEvent.direction == LaneDirection.EXIT,
            GateEvent.match_result == MatchResult.RESIDENT,
            GateEvent.paired_event_id.is_(None),
            GateEvent.captured_at <= now - GRACE,
        )
    )
    for event in exits_alone:
        counts["exit_without_entry"] += await _flag(
            db,
            society_id=event.society_id,
            kind=ReconciliationKind.EXIT_WITHOUT_ENTRY,
            gate_event_id=event.id,
            details=f"{event.plate_normalized} left at {event.captured_at:%Y-%m-%d %H:%M} UTC "
            "with no entry on record",
        )

    closer = aliased(GateEvent)
    later = aliased(GateEvent)
    unclosed = await db.scalars(
        select(entry).where(
            entry.direction == LaneDirection.ENTRY,
            entry.match_result == MatchResult.RESIDENT,
            ~exists().where(closer.paired_event_id == entry.id),
            exists().where(
                later.vehicle_id == entry.vehicle_id,
                later.direction == LaneDirection.ENTRY,
                later.captured_at > entry.captured_at,
            ),
        )
    )
    for event in unclosed:
        counts["entry_never_closed"] += await _flag(
            db,
            society_id=event.society_id,
            kind=ReconciliationKind.ENTRY_NEVER_CLOSED,
            gate_event_id=event.id,
            details=f"{event.plate_normalized} entered at {event.captured_at:%Y-%m-%d %H:%M} UTC "
            "and entered again without an exit",
        )

    stale = await db.scalars(
        select(Visit).where(
            Visit.status.in_(INSIDE_STATUSES),
            Visit.expected_exit_at <= now - timedelta(hours=settings.reconciliation_stale_hours),
        )
    )
    for visit in stale:
        counts["visit_not_closed"] += await _flag(
            db,
            society_id=visit.society_id,
            kind=ReconciliationKind.VISIT_NOT_CLOSED,
            visit_id=visit.id,
            details=f"Visit {visit.plate_normalized or ''} still '{visit.status.value}' "
            f"{settings.reconciliation_stale_hours} h after its time limit",
        )
    await db.commit()
    return counts


async def list_flags(
    db: AsyncSession, admin: User, page: PageRequest, *, resolved: bool | None = None
) -> PageResult[ReconciliationFlag]:
    statement = (
        select(ReconciliationFlag)
        .where(ReconciliationFlag.society_id == admin.society_id)
        .order_by(ReconciliationFlag.created_at.desc())
    )
    if resolved is True:
        statement = statement.where(ReconciliationFlag.resolved_at.is_not(None))
    elif resolved is False:
        statement = statement.where(ReconciliationFlag.resolved_at.is_(None))
    return await paginate(db, statement, page)


async def resolve_flag(db: AsyncSession, admin: User, flag_id: uuid.UUID) -> ReconciliationFlag:
    flag = await get_in_society(db, ReconciliationFlag, flag_id, admin.society_id)
    if flag.resolved_at is not None:
        raise ConflictError("Already resolved")
    flag.resolved_at = datetime.now(UTC)
    flag.resolved_by_id = admin.id
    await db.commit()
    return flag
