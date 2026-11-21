import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.models.enums import NotificationChannel, NotificationStatus, str_enum


class Notification(UUIDPrimaryKey, Timestamps, Base):
    """Log of every email / Telegram message we send (or try to), used in Phase 5."""

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
