"""The overstay escalation ladder (runs every minute from Celery Beat).

    time limit reached          -> visit OVERSTAYED; email the visitor and the residents
    + 30 min (reminder)         -> reminder email to the visitor and the residents
    + 60 min (escalation)       -> visit ESCALATED; a "call the resident" task on the guard console
    guard resolves the task     -> outcome saved; "vehicle left" also closes the visit

Each step happens **exactly once**: the status change is guarded by the state machine, each
email has a unique idempotency key, and a visit can have only one escalation task. If the
scheduler was down for an hour, one run catches up through every step that is due, in order.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.models import Approval, EscalationTask, Resident, User, Visit
from app.models.enums import (
    ApprovalStatus,
    EscalationOutcome,
    EscalationTaskStatus,
    UserRole,
    VisitStatus,
    VisitTrigger,
)
from app.schemas.escalation import EscalationRead
from app.services import emails, notifications, realtime, visitors
from app.services.errors import ConflictError, NotFoundError
from app.services.pagination import PageRequest, PageResult, paginate
from app.services.visit_state import INSIDE_STATUSES
from app.services.visits import transition_visit


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class LadderResult:
    overstayed: int = 0
    emails_queued: int = 0
    escalated: int = 0


async def _recipients(
    db: AsyncSession, visit: Visit
) -> list[tuple[str, str, str, uuid.UUID | None]]:
    """(role, name, email, user id) for the visitor and each resident with an email."""
    people: list[tuple[str, str, str, uuid.UUID | None]] = []
    if visit.visitor and visit.visitor.email:
        people.append(("visitor", visit.visitor.full_name, visit.visitor.email, None))
    residents = await db.scalars(
        select(User)
        .join(Resident, Resident.user_id == User.id)
        .where(Resident.flat_id == visit.flat_id, User.is_active.is_(True))
    )
    people += [("resident", r.full_name, r.email, r.id) for r in residents]
    return people


async def _queue_step(
    db: AsyncSession, visit: Visit, step: str, now: datetime, settings: Settings
) -> int:
    assert visit.expected_exit_at is not None  # noqa: S101 - only visits that entered get here
    visitor = visit.visitor.full_name if visit.visitor else "Your visitor"
    queued = 0
    for role, name, address, user_id in await _recipients(db, visit):
        to_visitor = role == "visitor"
        if step == "overstay_notice":
            email = emails.overstay_notice(
                name, visitor, visit.flat.label, visit.expected_exit_at, to_visitor=to_visitor
            )
        else:
            over = int((now - visit.expected_exit_at).total_seconds() // 60)
            email = emails.overstay_reminder(
                name, visitor, visit.flat.label, over, to_visitor=to_visitor
            )
        key = f"visit:{visit.id}:{step}:{role}:{user_id or 'visitor'}"
        queued += await notifications.queue_email(
            db,
            society_id=visit.society_id,
            kind=step,
            to=address,
            email=email,
            key=key,
            user_id=user_id,
            visit_id=visit.id,
        )
    return queued


def _due_visits(statuses: set[VisitStatus], deadline: datetime) -> Select[Visit]:
    return (
        select(Visit)
        .options(selectinload(Visit.visitor), selectinload(Visit.flat))
        .where(Visit.status.in_(statuses), Visit.expected_exit_at <= deadline)
        .order_by(Visit.expected_exit_at)
        .execution_options(populate_existing=True)
    )


async def run_ladder(
    db: AsyncSession, redis: Redis, settings: Settings, now: datetime | None = None
) -> LadderResult:
    now = now or utcnow()
    result = LadderResult()
    reminder = timedelta(minutes=settings.overstay_reminder_minutes)
    escalate = timedelta(minutes=settings.overstay_escalation_minutes)
    changed: list[Visit] = []

    # 1. Time's up.
    for visit in await db.scalars(_due_visits({VisitStatus.INSIDE}, now)):
        await transition_visit(
            db, settings, visit, VisitTrigger.OVERSTAY, at=now, note="time limit passed"
        )
        result.overstayed += 1
        result.emails_queued += await _queue_step(db, visit, "overstay_notice", now, settings)
        changed.append(visit)
    await db.flush()

    # 2. Reminder (also for escalated visits that missed it while the scheduler was down).
    for visit in await db.scalars(
        _due_visits({VisitStatus.OVERSTAYED, VisitStatus.ESCALATED}, now - reminder)
    ):
        result.emails_queued += await _queue_step(db, visit, "overstay_reminder", now, settings)

    # 3. Escalate to the guard.
    new_tasks: list[uuid.UUID] = []
    for visit in await db.scalars(_due_visits({VisitStatus.OVERSTAYED}, now - escalate)):
        task_id = await db.scalar(
            insert(EscalationTask)
            .values(id=uuid.uuid4(), visit_id=visit.id, status=EscalationTaskStatus.OPEN)
            .on_conflict_do_nothing(index_elements=["visit_id"])
            .returning(EscalationTask.id)
        )
        await transition_visit(
            db, settings, visit, VisitTrigger.ESCALATE, at=now, note="call the resident"
        )
        result.escalated += 1
        changed.append(visit)
        if task_id is not None:
            new_tasks.append(task_id)
    await db.commit()

    for visit in {v.id: v for v in changed}.values():
        await visitors.publish_visit(
            redis, db, await visitors.load_visit(db, visit.id), "visit.updated"
        )
    for task_id in new_tasks:
        task = await load_task(db, task_id)
        await realtime.publish(
            redis,
            [realtime.console_channel(task.visit.society_id)],
            "escalation.created",
            task_read(task),
        )
    return result


async def sweep_approvals(db: AsyncSession, redis: Redis, now: datetime | None = None) -> int:
    """Safety net for lost timeout jobs: time out every overdue pending approval."""
    now = now or utcnow()
    overdue = await db.scalars(
        select(Approval.id).where(
            Approval.status == ApprovalStatus.PENDING, Approval.expires_at <= now
        )
    )
    count = 0
    for approval_id in list(overdue):
        count += await visitors.expire_approval(db, redis, approval_id)
    return count


# --- Guard tasks -------------------------------------------------------------------------


def task_read(task: EscalationTask) -> EscalationRead:
    return EscalationRead(
        id=task.id,
        status=task.status,
        outcome=task.outcome,
        notes=task.notes,
        created_at=task.created_at,
        resolved_at=task.resolved_at,
        resolved_by_id=task.resolved_by_id,
        visit=visitors.visit_read(task.visit),
    )


def _tasks() -> Select[EscalationTask]:
    return select(EscalationTask).options(
        selectinload(EscalationTask.visit).selectinload(Visit.visitor),
        selectinload(EscalationTask.visit).selectinload(Visit.flat),
    )


async def load_task(db: AsyncSession, task_id: uuid.UUID) -> EscalationTask:
    task = await db.scalar(
        _tasks().where(EscalationTask.id == task_id).execution_options(populate_existing=True)
    )
    if task is None:
        raise NotFoundError("Escalation task not found")
    return task


async def list_tasks(
    db: AsyncSession, staff: User, page: PageRequest, *, status: EscalationTaskStatus | None = None
) -> PageResult[EscalationTask]:
    statement = (
        _tasks()
        .join(Visit, Visit.id == EscalationTask.visit_id)
        .where(Visit.society_id == staff.society_id)
        .order_by(EscalationTask.created_at.desc())
    )
    if status:
        statement = statement.where(EscalationTask.status == status)
    return await paginate(db, statement, page)


async def resolve_task(
    db: AsyncSession,
    redis: Redis,
    settings: Settings,
    staff: User,
    task_id: uuid.UUID,
    outcome: EscalationOutcome,
    notes: str | None,
) -> EscalationTask:
    task = await load_task(db, task_id)
    if task.visit.society_id != staff.society_id or staff.role is UserRole.RESIDENT:
        raise NotFoundError("Escalation task not found")
    if task.status is EscalationTaskStatus.RESOLVED:
        raise ConflictError("This task is already resolved")
    task.status = EscalationTaskStatus.RESOLVED
    task.outcome = outcome
    task.notes = notes
    task.resolved_at = utcnow()
    task.resolved_by_id = staff.id
    if outcome is EscalationOutcome.VEHICLE_LEFT and task.visit.status in INSIDE_STATUSES:
        await transition_visit(
            db,
            settings,
            task.visit,
            VisitTrigger.EXIT,
            at=task.resolved_at,
            actor_id=staff.id,
            note="guard confirmed the vehicle left",
        )
    await db.commit()
    task = await load_task(db, task.id)
    await realtime.publish(
        redis, [realtime.console_channel(staff.society_id)], "escalation.resolved", task_read(task)
    )
    return task
