"""The visit state machine, tested without a database."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.models.enums import VisitStatus, VisitTrigger
from app.services.visit_state import (
    INITIAL_STATUSES,
    INSIDE_STATUSES,
    TERMINAL_STATUSES,
    TRANSITIONS,
    IllegalTransitionError,
    apply_transition,
    next_status,
)

S = VisitStatus
T = VisitTrigger
NOON = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)
FOUR_HOURS = timedelta(hours=4)


@dataclass
class FakeVisit:
    status: VisitStatus
    entered_at: datetime | None = None
    expected_exit_at: datetime | None = None
    exited_at: datetime | None = None


# Every legal move, written out by hand so the test doesn't just re-read the table.
LEGAL = [
    (S.PENDING_APPROVAL, T.APPROVE, S.APPROVED),
    (S.PENDING_APPROVAL, T.DENY, S.DENIED),
    (S.PENDING_APPROVAL, T.EXPIRE, S.EXPIRED),
    (S.APPROVED, T.ENTER, S.INSIDE),
    (S.APPROVED, T.EXPIRE, S.EXPIRED),
    (S.INSIDE, T.OVERSTAY, S.OVERSTAYED),
    (S.INSIDE, T.EXIT, S.EXITED),
    (S.OVERSTAYED, T.ESCALATE, S.ESCALATED),
    (S.OVERSTAYED, T.EXIT, S.EXITED),
    (S.ESCALATED, T.EXIT, S.EXITED),
]
LEGAL_PAIRS = {(current, trigger) for current, trigger, _ in LEGAL}
ILLEGAL = [
    (current, trigger) for current in S for trigger in T if (current, trigger) not in LEGAL_PAIRS
]


@pytest.mark.parametrize(("current", "trigger", "expected"), LEGAL)
def test_legal_transitions(current: S, trigger: T, expected: S) -> None:
    assert next_status(current, trigger) is expected


@pytest.mark.parametrize(("current", "trigger"), ILLEGAL)
def test_every_other_transition_is_illegal(current: S, trigger: T) -> None:
    with pytest.raises(IllegalTransitionError) as error:
        next_status(current, trigger)
    assert error.value.current is current
    assert error.value.trigger is trigger


def test_rule_table_matches_the_documented_moves() -> None:
    assert {(c, t): n for c, t, n in LEGAL} == dict(TRANSITIONS)
    # 8 statuses x 7 triggers: 10 legal moves, 46 illegal ones.
    assert len(ILLEGAL) == len(S) * len(T) - len(LEGAL)


def test_status_groups() -> None:
    assert {S.EXITED, S.DENIED, S.EXPIRED} == TERMINAL_STATUSES
    assert {S.INSIDE, S.OVERSTAYED, S.ESCALATED} == INSIDE_STATUSES
    assert {S.PENDING_APPROVAL, S.APPROVED} == INITIAL_STATUSES


def test_enter_sets_entry_time_and_deadline() -> None:
    visit = FakeVisit(status=S.APPROVED)
    change = apply_transition(visit, T.ENTER, at=NOON, time_limit=FOUR_HOURS)

    assert visit.status is S.INSIDE
    assert visit.entered_at == NOON
    assert visit.expected_exit_at == NOON + FOUR_HOURS
    assert (change.from_status, change.to_status, change.trigger) == (S.APPROVED, S.INSIDE, T.ENTER)


def test_enter_keeps_an_agreed_exit_time() -> None:
    agreed = NOON + timedelta(hours=1, minutes=30)  # e.g. a resident-set service visit
    visit = FakeVisit(status=S.APPROVED, expected_exit_at=agreed)
    apply_transition(visit, T.ENTER, at=NOON, time_limit=FOUR_HOURS)
    assert visit.expected_exit_at == agreed


def test_enter_without_any_time_limit_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="time limit"):
        apply_transition(FakeVisit(status=S.APPROVED), T.ENTER, at=NOON)


def test_exit_sets_exit_time() -> None:
    visit = FakeVisit(status=S.OVERSTAYED, entered_at=NOON)
    apply_transition(visit, T.EXIT, at=NOON + timedelta(hours=5))
    assert visit.status is S.EXITED
    assert visit.exited_at == NOON + timedelta(hours=5)


def test_illegal_transition_changes_nothing() -> None:
    visit = FakeVisit(status=S.EXITED, exited_at=NOON)
    with pytest.raises(IllegalTransitionError, match="Can't 'enter' a visit that is 'exited'"):
        apply_transition(visit, T.ENTER, at=NOON + timedelta(hours=1), time_limit=FOUR_HOURS)
    assert visit == FakeVisit(status=S.EXITED, exited_at=NOON)


def test_naive_times_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        apply_transition(FakeVisit(status=S.INSIDE), T.EXIT, at=datetime(2026, 11, 21, 12, 0))


def test_full_overstay_journey() -> None:
    visit = FakeVisit(status=S.PENDING_APPROVAL)
    steps = [T.APPROVE, T.ENTER, T.OVERSTAY, T.ESCALATE, T.EXIT]
    seen = [
        apply_transition(visit, step, at=NOON, time_limit=FOUR_HOURS).to_status for step in steps
    ]
    assert seen == [S.APPROVED, S.INSIDE, S.OVERSTAYED, S.ESCALATED, S.EXITED]
