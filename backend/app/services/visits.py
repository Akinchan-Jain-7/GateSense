"""Saving visit status changes.

The rules are in `visit_state.py` (pure). This module is the only place that changes a
visit's status in the database: it applies the rule and writes a `visit_status_changes`
row in the same transaction, so the history can never disagree with the visit.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import Visit, VisitStatusChange
from app.models.enums import VisitCategory, VisitTrigger
from app.services.visit_state import StatusChange, apply_transition


def time_limit(settings: Settings, category: VisitCategory) -> timedelta:
    minutes = {
        VisitCategory.GUEST: settings.visit_limit_guest_minutes,
        VisitCategory.DELIVERY: settings.visit_limit_delivery_minutes,
        VisitCategory.CAB: settings.visit_limit_cab_minutes,
        VisitCategory.SERVICE: settings.visit_limit_service_minutes,
    }[category]
    return timedelta(minutes=minutes)


def transition_visit(
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
    change = apply_transition(
        visit, trigger, at=at, time_limit=time_limit(settings, visit.category)
    )
    if trigger is VisitTrigger.ENTER and gate_event_id is not None:
        visit.entry_event_id = gate_event_id
    elif trigger is VisitTrigger.EXIT and gate_event_id is not None:
        visit.exit_event_id = gate_event_id
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
