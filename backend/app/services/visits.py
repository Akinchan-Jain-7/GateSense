"""Creating visits and saving their status changes.

The rules are in `visit_state.py` (pure). This module is the only place that changes a
visit's status in the database: it applies the rule and writes a `visit_status_changes`
row in the same transaction, so the history can never disagree with the visit.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import Visit, VisitStatusChange
from app.models.enums import VisitCategory, VisitStatus, VisitTrigger
from app.services.errors import InvalidInputError
from app.services.society_settings import visit_limits
from app.services.visit_state import INITIAL_STATUSES, StatusChange, apply_transition


async def time_limit(db: AsyncSession, settings: Settings, visit: Visit) -> timedelta:
    """An agreed duration (e.g. a resident-set service visit) beats the category limit."""
    if visit.duration_minutes:
        return timedelta(minutes=visit.duration_minutes)
    limits = await visit_limits(db, settings, visit.society_id)
    return limits.for_category(visit.category)


async def start_visit(
    db: AsyncSession,
    *,
    society_id: uuid.UUID,
    flat_id: uuid.UUID,
    category: VisitCategory,
    status: VisitStatus,
    at: datetime,
    note: str,
    plate: str | None = None,
    visitor_id: uuid.UUID | None = None,
    guest_pass_id: uuid.UUID | None = None,
    purpose: str | None = None,
    duration_minutes: int | None = None,
    registered_by_id: uuid.UUID | None = None,
    approved_by_id: uuid.UUID | None = None,
) -> Visit:
    """Create a visit in its first status, with the first history row. Flushes, the caller
    commits."""
    if status not in INITIAL_STATUSES:
        raise InvalidInputError(f"A visit can't start as '{status.value}'")
    visit = Visit(
        id=uuid.uuid4(),
        society_id=society_id,
        flat_id=flat_id,
        category=category,
        status=status,
        plate_normalized=plate,
        visitor_id=visitor_id,
        guest_pass_id=guest_pass_id,
        purpose=purpose,
        duration_minutes=duration_minutes,
        registered_by_id=registered_by_id,
        approved_by_id=approved_by_id,
    )
    db.add(visit)
    await db.flush()  # the history row points at the visit
    db.add(
        VisitStatusChange(
            visit_id=visit.id,
            from_status=None,
            to_status=status,
            trigger=None,
            changed_at=at,
            actor_id=registered_by_id,
            note=note,
        )
    )
    return visit


async def transition_visit(
    db: AsyncSession,
    settings: Settings,
    visit: Visit,
    trigger: VisitTrigger,
    *,
    at: datetime,
    actor_id: uuid.UUID | None = None,
    gate_event_id: uuid.UUID | None = None,
    note: str | None = None,
) -> StatusChange:
    """Apply a trigger to a visit and log it. The caller commits.

    Raises IllegalTransitionError (→ 409) if the move isn't allowed.
    """
    limit = await time_limit(db, settings, visit)
    change = apply_transition(visit, trigger, at=at, time_limit=limit)
    if trigger is VisitTrigger.ENTER and gate_event_id is not None:
        visit.entry_event_id = gate_event_id
    elif trigger is VisitTrigger.EXIT and gate_event_id is not None:
        visit.exit_event_id = gate_event_id
    elif trigger is VisitTrigger.APPROVE and actor_id is not None:
        visit.approved_by_id = actor_id
    db.add(
        VisitStatusChange(
            visit_id=visit.id,
            from_status=change.from_status,
            to_status=change.to_status,
            trigger=trigger,
            changed_at=at,
            actor_id=actor_id,
            gate_event_id=gate_event_id,
            note=note,
        )
    )
    return change
