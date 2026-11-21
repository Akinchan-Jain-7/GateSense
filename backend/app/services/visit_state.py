"""The visit state machine: which status changes are allowed, and what each one sets.

This module is *pure*: no database, no clock, no I/O. It gets a visit, a trigger and a
time, and either applies the change or raises `IllegalTransitionError`. That makes every
rule testable in microseconds, and lets the API, the camera pipeline and the Celery jobs
(Phase 5) all go through the same rules. Saving and logging happen in `services/visits.py`.

    PENDING_APPROVAL --approve--> APPROVED --enter--> INSIDE --exit--> EXITED
           |                          |                  |
         deny/expire               expire             overstay
           v                          v                  v
     DENIED / EXPIRED              EXPIRED          OVERSTAYED --escalate--> ESCALATED
                                                         |                       |
                                                       exit                    exit
                                                         v                       v
                                                       EXITED                  EXITED
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from app.models.enums import VisitStatus, VisitTrigger
from app.services.errors import ConflictError

S = VisitStatus
T = VisitTrigger

# The whole rule book: (current status, trigger) -> new status. Anything missing is illegal.
TRANSITIONS: Mapping[tuple[VisitStatus, VisitTrigger], VisitStatus] = {
    (S.PENDING_APPROVAL, T.APPROVE): S.APPROVED,
    (S.PENDING_APPROVAL, T.DENY): S.DENIED,
    (S.PENDING_APPROVAL, T.EXPIRE): S.EXPIRED,
    (S.APPROVED, T.ENTER): S.INSIDE,
    (S.APPROVED, T.EXPIRE): S.EXPIRED,
    (S.INSIDE, T.OVERSTAY): S.OVERSTAYED,
    (S.INSIDE, T.EXIT): S.EXITED,
    (S.OVERSTAYED, T.ESCALATE): S.ESCALATED,
    (S.OVERSTAYED, T.EXIT): S.EXITED,
    (S.ESCALATED, T.EXIT): S.EXITED,
}

# A new visit starts waiting for the resident, or already approved (e.g. from a guest pass).
INITIAL_STATUSES = frozenset({S.PENDING_APPROVAL, S.APPROVED})

# The vehicle is on the premises: an exit read closes these visits.
INSIDE_STATUSES = frozenset({S.INSIDE, S.OVERSTAYED, S.ESCALATED})

# No way out: the visit is over.
TERMINAL_STATUSES = frozenset(set(S) - {current for current, _ in TRANSITIONS})


class IllegalTransitionError(ConflictError):
    """The trigger isn't allowed from the visit's current status. → 409"""

    def __init__(self, current: VisitStatus, trigger: VisitTrigger) -> None:
        super().__init__(f"Can't '{trigger.value}' a visit that is '{current.value}'")
        self.current = current
        self.trigger = trigger


def next_status(current: VisitStatus, trigger: VisitTrigger) -> VisitStatus:
    try:
        return TRANSITIONS[(current, trigger)]
    except KeyError:
        raise IllegalTransitionError(current, trigger) from None


class VisitLike(Protocol):
    """The fields of a visit the state machine reads and writes (the Visit model has them)."""

    status: VisitStatus
    entered_at: datetime | None
    expected_exit_at: datetime | None
    exited_at: datetime | None


@dataclass(frozen=True)
class StatusChange:
    from_status: VisitStatus
    to_status: VisitStatus
    trigger: VisitTrigger
    at: datetime


def apply_transition(
    visit: VisitLike,
    trigger: VisitTrigger,
    *,
    at: datetime,
    time_limit: timedelta | None = None,
) -> StatusChange:
    """Move `visit` to its next status and set the timestamps that go with it.

    - ENTER sets `entered_at`, and `expected_exit_at = at + time_limit` unless a time was
      already agreed (e.g. a resident set the duration of a service visit).
    - EXIT sets `exited_at`.
    Raises IllegalTransitionError (and changes nothing) if the move isn't allowed.
    """
    if at.tzinfo is None:
        raise ValueError("transition times must be timezone-aware")
    new_status = next_status(visit.status, trigger)
    change = StatusChange(from_status=visit.status, to_status=new_status, trigger=trigger, at=at)

    if trigger is T.ENTER:
        visit.entered_at = at
        if visit.expected_exit_at is None:
            if time_limit is None:
                raise ValueError("ENTER needs a time limit when no exit time was agreed")
            visit.expected_exit_at = at + time_limit
    elif trigger is T.EXIT:
        visit.exited_at = at

    visit.status = new_status
    return change
