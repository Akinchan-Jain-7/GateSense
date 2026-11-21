import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.models.enums import (
    AlertKind,
    AlertSeverity,
    LaneDirection,
    MatchResult,
    ReviewReason,
    str_enum,
)


class Gate(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "gates"

    society_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societies.id"), index=True)
    name: Mapped[str] = mapped_column(String(60))  # "Main Gate"
    location: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Device(UUIDPrimaryKey, Timestamps, Base):
    """A camera (ANPR worker) watching one lane of one gate.

    Devices authenticate with an API key. We store only a SHA-256 hash of the key,
    plus its first characters (`api_key_prefix`) so an admin can tell keys apart.
    """

    __tablename__ = "devices"

    gate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gates.id"), index=True)
    name: Mapped[str] = mapped_column(String(60))  # "Main Gate - entry camera"
    direction: Mapped[LaneDirection] = mapped_column(str_enum(LaneDirection, "lane_direction"))
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    api_key_prefix: Mapped[str] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    gate: Mapped[Gate] = relationship(lazy="raise")


class GateEvent(UUIDPrimaryKey, Base):
    """One plate read sent by a device, and what the gate-event engine decided about it.

    See app/services/gate_events.py for the pipeline that fills these columns in.
    """

    __tablename__ = "gate_events"
    __table_args__ = (
        Index("ix_gate_events_society_captured", "society_id", "captured_at"),
        # The guard review queue: unresolved events that need a human look.
        Index(
            "ix_gate_events_review_queue",
            "society_id",
            "captured_at",
            postgresql_where=text("needs_review AND reviewed_at IS NULL"),
        ),
    )

    society_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societies.id"))
    gate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gates.id"))
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), index=True)
    direction: Mapped[LaneDirection] = mapped_column(str_enum(LaneDirection, "lane_direction"))
    plate_raw: Mapped[str] = mapped_column(String(32))  # exactly what OCR returned
    # The repaired plate (None if the text couldn't be made into a valid plate).
    plate_normalized: Mapped[str | None] = mapped_column(String(12), index=True)
    # How many look-alike characters were swapped to get plate_normalized (O->0 etc.).
    ocr_fixes: Mapped[int | None] = mapped_column(SmallInteger)
    confidence: Mapped[float] = mapped_column(Float)
    snapshot_path: Mapped[str | None] = mapped_column(String(255))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Hash of (device, plate text, capture time): a retried upload is stored only once.
    event_hash: Mapped[str] = mapped_column(String(64), unique=True)
    match_result: Mapped[MatchResult] = mapped_column(str_enum(MatchResult, "match_result"))
    # Edit distance to the plate we matched: 0 = exact, 1 = fuzzy (one character off).
    match_distance: Mapped[int | None] = mapped_column(SmallInteger)
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL")
    )
    # use_alter: visits and gate_events point at each other, so this foreign key is
    # added after both tables exist.
    visit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("visits.id", use_alter=True, ondelete="SET NULL")
    )
    # On a resident EXIT event: the ENTRY event it closes. Unique, so an entry is closed
    # once. Entries never closed and exits with nothing to close are what the nightly
    # reconciliation (Phase 5) reports.
    paired_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gate_events.id", ondelete="SET NULL"), unique=True
    )
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reason: Mapped[ReviewReason | None] = mapped_column(
        str_enum(ReviewReason, "review_reason")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class PlateCorrection(UUIDPrimaryKey, Timestamps, Base):
    """A guard's fix of a low-confidence read. Kept as labelled data for retraining OCR."""

    __tablename__ = "plate_corrections"

    gate_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gate_events.id", ondelete="CASCADE"), index=True
    )
    original_plate: Mapped[str] = mapped_column(String(32))
    corrected_plate: Mapped[str] = mapped_column(String(12))
    corrected_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class Alert(UUIDPrimaryKey, Timestamps, Base):
    """Something the guard must see now, e.g. a watchlisted plate at the gate.

    Stays on the guard console until a guard acknowledges it.
    """

    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_society_open", "society_id", "acknowledged_at"),)

    society_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societies.id"))
    kind: Mapped[AlertKind] = mapped_column(str_enum(AlertKind, "alert_kind"))
    severity: Mapped[AlertSeverity] = mapped_column(str_enum(AlertSeverity, "alert_severity"))
    message: Mapped[str] = mapped_column(Text)
    gate_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gate_events.id", ondelete="CASCADE"), index=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
