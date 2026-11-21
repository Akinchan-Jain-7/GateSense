"""Visitors at the gate and the approval flow.

    guard registers visitor ──► visit PENDING_APPROVAL + approval (expires in 3 min)
        │                         ├─► WebSocket: flat's residents + guard console
        │                         ├─► Telegram: residents who linked the bot
        │                         └─► timeout job scheduled for expires_at
        ├─ resident approves ──► visit APPROVED (and INSIDE at once if the car is waiting)
        ├─ resident denies   ──► visit DENIED
        └─ nobody answers    ──► approval TIMED_OUT ─► the guard approves or denies

Deciding is idempotent (pressing "Approve" twice, or on web *and* Telegram, is fine) and
race-safe (the approval row is locked while deciding, so two residents can't both win).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.models import Approval, Flat, GateEvent, Resident, User, Visit, Visitor
from app.models.enums import (
    ApprovalChannel,
    ApprovalStatus,
    LaneDirection,
    MatchResult,
    UserRole,
    VisitStatus,
    VisitTrigger,
)
from app.schemas.visit import ApprovalRead, VisitorRegistration, VisitRead, mask_phone
from app.services import realtime
from app.services.db_helpers import get_in_society
from app.services.errors import ConflictError, NotFoundError
from app.services.pagination import PageRequest, PageResult, paginate
from app.services.plates import normalize_typed_plate
from app.services.society_settings import visit_limits
from app.services.visit_state import INSIDE_STATUSES
from app.services.visits import start_visit, transition_visit
from app.workers.jobs import JobQueue


def utcnow() -> datetime:
    return datetime.now(UTC)


# --- Read models ------------------------------------------------------------------------


def visit_read(visit: Visit) -> VisitRead:
    visitor = visit.visitor
    return VisitRead(
        id=visit.id,
        flat_id=visit.flat_id,
        flat_label=visit.flat.label,
        category=visit.category,
        status=visit.status,
        purpose=visit.purpose,
        plate_normalized=visit.plate_normalized,
        visitor_name=visitor.full_name if visitor else None,
        visitor_phone=mask_phone(visitor.phone) if visitor else None,
        guest_pass_id=visit.guest_pass_id,
        duration_minutes=visit.duration_minutes,
        entered_at=visit.entered_at,
        expected_exit_at=visit.expected_exit_at,
        exited_at=visit.exited_at,
        approved_by_id=visit.approved_by_id,
        registered_by_id=visit.registered_by_id,
        entry_event_id=visit.entry_event_id,
        created_at=visit.created_at,
    )


def approval_read(approval: Approval) -> ApprovalRead:
    return ApprovalRead(
        id=approval.id,
        status=approval.status,
        requested_at=approval.requested_at,
        expires_at=approval.expires_at,
        decided_at=approval.decided_at,
        decided_by_id=approval.decided_by_id,
        channel=approval.channel,
        visit=visit_read(approval.visit),
    )


def _visits() -> Select[Visit]:
    return select(Visit).options(selectinload(Visit.visitor), selectinload(Visit.flat))


def _approvals() -> Select[Approval]:
    return select(Approval).options(
        selectinload(Approval.visit).selectinload(Visit.visitor),
        selectinload(Approval.visit).selectinload(Visit.flat),
    )


async def load_visit(db: AsyncSession, visit_id: uuid.UUID) -> Visit:
    visit = await db.scalar(
        _visits().where(Visit.id == visit_id).execution_options(populate_existing=True)
    )
    if visit is None:
        raise NotFoundError("Visit not found")
    return visit


async def load_approval(
    db: AsyncSession, approval_id: uuid.UUID, *, lock: bool = False
) -> Approval:
    statement = (
        _approvals().where(Approval.id == approval_id).execution_options(populate_existing=True)
    )
    if lock:
        statement = statement.with_for_update(of=Approval)
    approval = await db.scalar(statement)
    if approval is None:
        raise NotFoundError("Approval not found")
    return approval


async def flat_resident_ids(db: AsyncSession, flat_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await db.scalars(
        select(Resident.user_id)
        .join(User, User.id == Resident.user_id)
        .where(Resident.flat_id == flat_id, User.is_active.is_(True))
    )
    return list(rows)


async def resident_flat_ids(db: AsyncSession, user: User) -> list[uuid.UUID]:
    return list(await db.scalars(select(Resident.flat_id).where(Resident.user_id == user.id)))


async def _ensure_flat_access(db: AsyncSession, user: User, visit: Visit) -> None:
    """Residents may act only on their own flats' visits (others get 404, like a missing id)."""
    if visit.society_id != user.society_id:
        raise NotFoundError("Not found")
    if user.role is UserRole.RESIDENT and visit.flat_id not in await resident_flat_ids(db, user):
        raise NotFoundError("Not found")


async def publish_visit(redis: Redis, db: AsyncSession, visit: Visit, event_type: str) -> None:
    residents = await flat_resident_ids(db, visit.flat_id)
    channels = [realtime.console_channel(visit.society_id)]
    channels += [realtime.user_channel(r) for r in residents]
    await realtime.publish(redis, channels, event_type, visit_read(visit))


async def publish_approval(
    redis: Redis, db: AsyncSession, approval: Approval, event_type: str
) -> None:
    residents = await flat_resident_ids(db, approval.visit.flat_id)
    channels = [realtime.console_channel(approval.visit.society_id)]
    channels += [realtime.user_channel(r) for r in residents]
    await realtime.publish(redis, channels, event_type, approval_read(approval))


# --- Registration -----------------------------------------------------------------------


async def _find_or_create_visitor(
    db: AsyncSession, society_id: uuid.UUID, data: VisitorRegistration
) -> Visitor:
    """Repeat visitors are recognised by phone number within the society."""
    visitor = await db.scalar(
        select(Visitor).where(Visitor.society_id == society_id, Visitor.phone == data.phone)
    )
    if visitor is None:
        visitor = Visitor(society_id=society_id, phone=data.phone, full_name=data.full_name)
        db.add(visitor)
    visitor.full_name = data.full_name
    if data.email:
        visitor.email = str(data.email)
    await db.flush()
    return visitor


async def _waiting_entry_event(db: AsyncSession, guard: User, event_id: uuid.UUID) -> GateEvent:
    event = await get_in_society(db, GateEvent, event_id, guard.society_id)
    if event.direction is not LaneDirection.ENTRY:
        raise ConflictError("That read is from an exit lane")
    if event.visit_id is not None or event.vehicle_id is not None:
        raise ConflictError("That read already belongs to a visit or a resident vehicle")
    if event.match_result not in {MatchResult.UNKNOWN, MatchResult.LOW_CONFIDENCE}:
        raise ConflictError(f"That read was matched as '{event.match_result.value}'")
    return event


@dataclass(frozen=True)
class Registered:
    visit: Visit
    approval: Approval


async def register_visitor(
    db: AsyncSession,
    redis: Redis,
    jobs: JobQueue,
    settings: Settings,
    guard: User,
    data: VisitorRegistration,
) -> Registered:
    now = utcnow()
    flat = await get_in_society(db, Flat, data.flat_id, guard.society_id)
    event = (
        await _waiting_entry_event(db, guard, data.gate_event_id) if data.gate_event_id else None
    )
    plate = (
        normalize_typed_plate(data.plate)
        if data.plate
        else (event.plate_normalized if event else None)
    )
    visitor = await _find_or_create_visitor(db, guard.society_id, data)

    visit = await start_visit(
        db,
        society_id=guard.society_id,
        flat_id=flat.id,
        category=data.category,
        status=VisitStatus.PENDING_APPROVAL,
        at=now,
        note="registered by guard",
        plate=plate,
        visitor_id=visitor.id,
        purpose=data.purpose,
        duration_minutes=data.duration_minutes,
        registered_by_id=guard.id,
    )
    if event is not None:
        # The car is waiting at the barrier: link the read so approval admits it at once.
        event.visit_id = visit.id
        event.match_result = MatchResult.VISITOR
        visit.entry_event_id = event.id

    limits = await visit_limits(db, settings, guard.society_id)
    approval = Approval(
        visit_id=visit.id,
        status=ApprovalStatus.PENDING,
        requested_at=now,
        expires_at=now + limits.approval_timeout,
    )
    residents = await flat_resident_ids(db, flat.id)
    if not residents:
        # Nobody can answer: go straight to the guard.
        approval.status = ApprovalStatus.TIMED_OUT
        approval.expires_at = now
    db.add(approval)
    await db.commit()

    approval = await load_approval(db, approval.id)
    await publish_approval(
        redis, db, approval, "approval.requested" if residents else "approval.timed_out"
    )
    if residents:
        jobs.approval_timeout(approval.id, approval.expires_at)
        jobs.notify_approval(approval.id)
    return Registered(visit=approval.visit, approval=approval)


# --- Decisions --------------------------------------------------------------------------


async def _apply_decision(
    db: AsyncSession,
    settings: Settings,
    visit: Visit,
    approve: bool,
    actor_id: uuid.UUID,
    at: datetime,
) -> None:
    await transition_visit(
        db,
        settings,
        visit,
        VisitTrigger.APPROVE if approve else VisitTrigger.DENY,
        at=at,
        actor_id=actor_id,
    )
    if approve and visit.entry_event_id is not None:
        # The car has been waiting at the barrier since its read: let it in now.
        await transition_visit(
            db,
            settings,
            visit,
            VisitTrigger.ENTER,
            at=at,
            actor_id=actor_id,
            gate_event_id=visit.entry_event_id,
            note="admitted after approval",
        )


@dataclass(frozen=True)
class DecisionResult:
    approval: Approval
    changed: bool  # False = it was already decided this way (idempotent repeat)


async def decide_approval(
    db: AsyncSession,
    redis: Redis,
    settings: Settings,
    resident: User,
    approval_id: uuid.UUID,
    approve: bool,
    channel: ApprovalChannel,
) -> DecisionResult:
    now = utcnow()
    approval = await load_approval(db, approval_id, lock=True)
    await _ensure_flat_access(db, resident, approval.visit)
    wanted = ApprovalStatus.APPROVED if approve else ApprovalStatus.DENIED

    if approval.status is ApprovalStatus.PENDING and approval.expires_at <= now:
        approval.status = ApprovalStatus.TIMED_OUT  # the timeout job just hasn't run yet
        await db.commit()
        await publish_approval(redis, db, approval, "approval.timed_out")
        raise ConflictError("Too late: the request timed out and the guard decides now")
    if approval.status is wanted:
        await db.commit()  # nothing changed; ends the transaction (and the row lock)
        return DecisionResult(approval=approval, changed=False)
    if approval.status is not ApprovalStatus.PENDING:
        await db.commit()  # nothing changed; ends the transaction (and the row lock)
        raise ConflictError(f"Already decided: {approval.status.value.replace('_', ' ')}")

    approval.status = wanted
    approval.decided_at = now
    approval.decided_by_id = resident.id
    approval.channel = channel
    await _apply_decision(db, settings, approval.visit, approve, resident.id, now)
    await db.commit()
    approval = await load_approval(db, approval.id)
    await publish_approval(redis, db, approval, "approval.decided")
    return DecisionResult(approval=approval, changed=True)


async def expire_approval(db: AsyncSession, redis: Redis, approval_id: uuid.UUID) -> bool:
    """The timeout job. Safe to run twice, early or late; returns True if it timed out now."""
    approval = await load_approval(db, approval_id, lock=True)
    if approval.status is not ApprovalStatus.PENDING or approval.expires_at > utcnow():
        await db.commit()  # nothing changed; ends the transaction (and the row lock)
        return False
    approval.status = ApprovalStatus.TIMED_OUT
    await db.commit()
    await publish_approval(redis, db, approval, "approval.timed_out")
    return True


async def latest_approval(db: AsyncSession, visit_id: uuid.UUID) -> Approval | None:
    return await db.scalar(
        _approvals()
        .where(Approval.visit_id == visit_id)
        .order_by(Approval.requested_at.desc())
        .limit(1)
    )


async def guard_decide(
    db: AsyncSession,
    redis: Redis,
    settings: Settings,
    guard: User,
    visit_id: uuid.UUID,
    approve: bool,
) -> Visit:
    """The fallback after the timeout. While residents can still answer, the guard waits."""
    now = utcnow()
    visit = await load_visit(db, visit_id)
    await _ensure_flat_access(db, guard, visit)
    if visit.status is not VisitStatus.PENDING_APPROVAL:
        raise ConflictError(f"This visit is already {visit.status.value.replace('_', ' ')}")
    approval = await latest_approval(db, visit.id)
    if approval is not None and approval.status is ApprovalStatus.PENDING:
        if approval.expires_at > now:
            seconds = int((approval.expires_at - now).total_seconds())
            raise ConflictError(f"Residents can still answer for {seconds} s")
        approval.status = ApprovalStatus.TIMED_OUT
    await _apply_decision(db, settings, visit, approve, guard.id, now)
    await db.commit()
    visit = await load_visit(db, visit.id)
    await publish_visit(redis, db, visit, "visit.updated")
    return visit


async def manual_move(
    db: AsyncSession,
    redis: Redis,
    settings: Settings,
    guard: User,
    visit_id: uuid.UUID,
    trigger: VisitTrigger,
) -> Visit:
    """The guard marks an entry or exit by hand (camera missed it, walk-in visitor…)."""
    visit = await load_visit(db, visit_id)
    await _ensure_flat_access(db, guard, visit)
    await transition_visit(
        db, settings, visit, trigger, at=utcnow(), actor_id=guard.id, note="marked by guard"
    )
    await db.commit()
    visit = await load_visit(db, visit.id)
    await publish_visit(redis, db, visit, "visit.updated")
    return visit


# --- Lists ---------------------------------------------------------------------------------


async def list_visits(
    db: AsyncSession,
    user: User,
    page: PageRequest,
    *,
    status: VisitStatus | None = None,
    inside: bool | None = None,
    flat_id: uuid.UUID | None = None,
    q: str | None = None,
) -> PageResult[Visit]:
    statement = (
        _visits().where(Visit.society_id == user.society_id).order_by(Visit.created_at.desc())
    )
    if user.role is UserRole.RESIDENT:
        statement = statement.where(Visit.flat_id.in_(await resident_flat_ids(db, user)))
    if status:
        statement = statement.where(Visit.status == status)
    if inside is True:
        statement = statement.where(Visit.status.in_(INSIDE_STATUSES))
    if flat_id:
        statement = statement.where(Visit.flat_id == flat_id)
    if q:
        term = f"%{q.strip()}%"
        statement = statement.outerjoin(Visitor, Visitor.id == Visit.visitor_id).where(
            or_(Visit.plate_normalized.ilike(term.replace(" ", "")), Visitor.full_name.ilike(term))
        )
    return await paginate(db, statement, page)


async def get_visit(db: AsyncSession, user: User, visit_id: uuid.UUID) -> Visit:
    visit = await load_visit(db, visit_id)
    await _ensure_flat_access(db, user, visit)
    return visit


async def list_approvals(
    db: AsyncSession, user: User, page: PageRequest, *, status: ApprovalStatus | None = None
) -> PageResult[Approval]:
    statement = (
        _approvals()
        .join(Visit, Visit.id == Approval.visit_id)
        .where(Visit.society_id == user.society_id)
        .order_by(Approval.requested_at.desc())
    )
    if user.role is UserRole.RESIDENT:
        statement = statement.where(Visit.flat_id.in_(await resident_flat_ids(db, user)))
    if status:
        statement = statement.where(Approval.status == status)
    return await paginate(db, statement, page)
