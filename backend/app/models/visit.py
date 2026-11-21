import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.models.enums import (
    ApprovalChannel,
    ApprovalStatus,
    EscalationOutcome,
    EscalationTaskStatus,
    VisitCategory,
    VisitStatus,
    VisitTrigger,
    str_enum,
)


class Visitor(UUIDPrimaryKey, Timestamps, Base):
    """A person who visits. Personal data is purged after the retention period (Phase 5)."""

    __tablename__ = "visitors"

    society_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societies.id"), index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(20), index=True)
    email: Mapped[str | None] = mapped_column(String(254))


class Visit(UUIDPrimaryKey, Timestamps, Base):
    """One visit to one flat, moved through the visit state machine.

    Change `status` only through app/services/visits.py, which checks the move is legal
    (app/services/visit_state.py) and records it in `visit_status_changes`.
    """

    __tablename__ = "visits"

    society_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societies.id"))
    flat_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("flats.id"), index=True)
    visitor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("visitors.id", ondelete="SET NULL"), index=True
    )
    guest_pass_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("guest_passes.id", ondelete="SET NULL")
    )
    plate_normalized: Mapped[str | None] = mapped_column(String(12), index=True)
    category: Mapped[VisitCategory] = mapped_column(str_enum(VisitCategory, "visit_category"))
    purpose: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[VisitStatus] = mapped_column(str_enum(VisitStatus, "visit_status"), index=True)
    registered_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    entry_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gate_events.id", ondelete="SET NULL")
    )
    exit_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gate_events.id", ondelete="SET NULL")
    )
    entered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expected_exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VisitStatusChange(UUIDPrimaryKey, Base):
    """History of a visit: one row per status change, never updated or deleted."""

    __tablename__ = "visit_status_changes"

    visit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("visits.id", ondelete="CASCADE"), index=True
    )
    # None for the row that records the visit being created.
    # Each enum column needs its own name: it becomes the name of its CHECK constraint.
    from_status: Mapped[VisitStatus | None] = mapped_column(str_enum(VisitStatus, "from_status"))
    to_status: Mapped[VisitStatus] = mapped_column(str_enum(VisitStatus, "to_status"))
    trigger: Mapped[VisitTrigger | None] = mapped_column(str_enum(VisitTrigger, "visit_trigger"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Who or what caused it: a user (guard, resident), a camera read, or neither (a job).
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    gate_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gate_events.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(String(255))


class Approval(UUIDPrimaryKey, Timestamps, Base):
    """A request to a flat's residents to approve or deny a visit (3-minute timeout)."""

    __tablename__ = "approvals"

    visit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("visits.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        str_enum(ApprovalStatus, "approval_status"), default=ApprovalStatus.PENDING
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    channel: Mapped[ApprovalChannel | None] = mapped_column(
        str_enum(ApprovalChannel, "approval_channel")
    )


class GuestPass(UUIDPrimaryKey, Timestamps, Base):
    """Created by a resident ahead of time; matched by plate or by a one-time code."""

    __tablename__ = "guest_passes"
    __table_args__ = (
        CheckConstraint(
            "plate_normalized IS NOT NULL OR code_hash IS NOT NULL", name="plate_or_code"
        ),
        CheckConstraint("use_count <= max_uses", name="within_usage_limit"),
    )

    society_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societies.id"))
    flat_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("flats.id"), index=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    guest_name: Mapped[str] = mapped_column(String(120))
    guest_phone: Mapped[str | None] = mapped_column(String(20))
    category: Mapped[VisitCategory] = mapped_column(str_enum(VisitCategory, "visit_category"))
    plate_normalized: Mapped[str | None] = mapped_column(String(12), index=True)
    # The one-time code is shown to the resident once; only its hash is stored.
    code_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EscalationTask(UUIDPrimaryKey, Timestamps, Base):
    """A "call the resident" job on the guard console for an overstaying visit (Phase 5)."""

    __tablename__ = "escalation_tasks"

    visit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("visits.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[EscalationTaskStatus] = mapped_column(
        str_enum(EscalationTaskStatus, "escalation_task_status"),
        default=EscalationTaskStatus.OPEN,
        index=True,
    )
    outcome: Mapped[EscalationOutcome | None] = mapped_column(
        str_enum(EscalationOutcome, "escalation_outcome")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
