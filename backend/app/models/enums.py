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
    """What the gate-event engine (Phase 2) decided a plate read was."""

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
    """States of the visit state machine (rules arrive in Phase 2)."""

    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    INSIDE = "inside"
    OVERSTAYED = "overstayed"
    ESCALATED = "escalated"
    EXITED = "exited"
    DENIED = "denied"
    EXPIRED = "expired"


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
