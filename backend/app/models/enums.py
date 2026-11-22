"""Enumerations shared by models, schemas and services.

Stored as short strings (VARCHAR + CHECK constraint), not native Postgres enum types:
adding a value later is a simple constraint change instead of an `ALTER TYPE`.
"""

from enum import StrEnum

from sqlalchemy import Enum as SAEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    GUARD = "guard"
    RESIDENT = "resident"


class ResidentType(StrEnum):
    OWNER = "owner"
    TENANT = "tenant"
    FAMILY = "family"


class VehicleType(StrEnum):
    CAR = "car"
    TWO_WHEELER = "two_wheeler"


class LaneDirection(StrEnum):
    ENTRY = "entry"
    EXIT = "exit"


class MatchResult(StrEnum):
    """What the gate-event engine decided a plate read was."""

    RESIDENT = "resident"
    GUEST_PASS = "guest_pass"  # noqa: S105 - "pass" as in guest pass
    VISITOR = "visitor"
    WATCHLIST = "watchlist"
    UNKNOWN = "unknown"
    LOW_CONFIDENCE = "low_confidence"


class VisitCategory(StrEnum):
    GUEST = "guest"
    DELIVERY = "delivery"
    CAB = "cab"
    SERVICE = "service"


class VisitStatus(StrEnum):
    """States of the visit state machine. The rules live in app/services/visit_state.py."""

    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    INSIDE = "inside"
    OVERSTAYED = "overstayed"
    ESCALATED = "escalated"
    EXITED = "exited"
    DENIED = "denied"
    EXPIRED = "expired"


class VisitTrigger(StrEnum):
    """What happened to a visit; each trigger moves it to a new status (or is illegal)."""

    APPROVE = "approve"  # a resident (or the guard, after the timeout) said yes
    DENY = "deny"
    ENTER = "enter"  # the entry camera read the plate, or the guard let them in
    OVERSTAY = "overstay"  # the time limit passed while inside
    ESCALATE = "escalate"  # the overstay was escalated to the guard (call task)
    EXIT = "exit"  # the exit camera read the plate, or the guard marked the exit
    EXPIRE = "expire"  # never approved, or approved but never arrived


class ReviewReason(StrEnum):
    """Why a gate event was sent to the guard review queue."""

    LOW_CONFIDENCE = "low_confidence"  # OCR wasn't sure
    UNREADABLE = "unreadable"  # the text can't be turned into a valid plate
    AMBIGUOUS_MATCH = "ambiguous_match"  # close to two or more known plates


class AlertKind(StrEnum):
    WATCHLIST = "watchlist"


class AlertSeverity(StrEnum):
    HIGH = "high"
    NORMAL = "normal"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    TIMED_OUT = "timed_out"


class ApprovalChannel(StrEnum):
    WEB = "web"
    TELEGRAM = "telegram"
    GUARD = "guard"


class NotificationChannel(StrEnum):
    EMAIL = "email"
    TELEGRAM = "telegram"


class NotificationStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class EscalationTaskStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class ReconciliationKind(StrEnum):
    """What the nightly reconciliation found."""

    EXIT_WITHOUT_ENTRY = "exit_without_entry"  # a resident left but was never seen coming in
    ENTRY_NEVER_CLOSED = "entry_never_closed"  # seen coming in twice, never seen leaving between
    VISIT_NOT_CLOSED = "visit_not_closed"  # a visitor "inside" long after the time limit


class EscalationOutcome(StrEnum):
    REACHED = "reached"
    NOT_REACHED = "not_reached"
    VEHICLE_LEFT = "vehicle_left"


def str_enum(enum_cls: type[StrEnum], name: str) -> SAEnum:
    """Column type for a StrEnum: stores `.value` ("pending"), checked by a constraint."""
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda cls: [member.value for member in cls],
        validate_strings=True,
    )
