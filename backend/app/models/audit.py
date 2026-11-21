import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKey


class AuditLog(UUIDPrimaryKey, Base):
    """Append-only record of admin actions: who changed what, and how."""

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_society_created", "society_id", "created_at"),)

    society_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societies.id"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(60))  # "vehicle.create"
    entity_type: Mapped[str] = mapped_column(String(40))  # "vehicle"
    entity_id: Mapped[uuid.UUID | None]
    # What changed, e.g. {"colour": ["White", "Grey"]}. Never contains secrets.
    changes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
