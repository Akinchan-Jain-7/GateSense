import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.models.enums import (
    NotificationChannel,
    NotificationStatus,
    ReconciliationKind,
    str_enum,
)


class Notification(UUIDPrimaryKey, Timestamps, Base):
    """Every email / Telegram message we send (or try to).

    A row is created with the rendered message (status PENDING); the dispatcher job sends
    it and retries with backoff on failure. `idempotency_key` is unique, so a job that runs
    twice can never queue (or send) the same message twice.
    """

    __tablename__ = "notifications"

    society_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societies.id"))
    channel: Mapped[NotificationChannel] = mapped_column(
        str_enum(NotificationChannel, "notification_channel")
    )
    kind: Mapped[str] = mapped_column(String(60))  # e.g. "overstay_first_notice"
    recipient: Mapped[str] = mapped_column(String(254))  # email address or Telegram chat id
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    visit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("visits.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[NotificationStatus] = mapped_column(
        str_enum(NotificationStatus, "notification_status"),
        default=NotificationStatus.PENDING,
        index=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    # e.g. "visit:<id>:overstay_first_notice:visitor". Unique, so a retried job
    # can never send the same notification twice.
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The rendered message, kept so the log shows exactly what went out.
    subject: Mapped[str | None] = mapped_column(String(255))
    body_text: Mapped[str | None] = mapped_column(Text)
    body_html: Mapped[str | None] = mapped_column(Text)
    # Channel extras: Telegram buttons and the approval a request is about.
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # When the dispatcher may try again (exponential backoff after a failure).
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class ReconciliationFlag(UUIDPrimaryKey, Timestamps, Base):
    """Something the nightly reconciliation wants the admin to look at.

    Unique per (kind, subject): running the job again doesn't flag the same thing twice.
    (`subject_id` is the flagged gate event's or visit's id, never NULL, because Postgres
    treats NULLs as all different in a unique constraint.)
    """

    __tablename__ = "reconciliation_flags"
    __table_args__ = (UniqueConstraint("kind", "subject_id", name="one_flag_per_finding"),)

    society_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societies.id"), index=True)
    kind: Mapped[ReconciliationKind] = mapped_column(
        str_enum(ReconciliationKind, "reconciliation_kind")
    )
    subject_id: Mapped[uuid.UUID]
    gate_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gate_events.id", ondelete="CASCADE")
    )
    visit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("visits.id", ondelete="CASCADE"))
    details: Mapped[str] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
