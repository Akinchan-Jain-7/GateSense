import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.models.enums import VehicleType, str_enum
from app.models.society import Flat


class Vehicle(UUIDPrimaryKey, Timestamps, Base):
    """A resident vehicle. It belongs to a flat (any resident of the flat may drive it)."""

    __tablename__ = "vehicles"
    __table_args__ = (UniqueConstraint("society_id", "plate_normalized"),)

    society_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societies.id"))
    flat_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("flats.id"), index=True)
    plate_raw: Mapped[str] = mapped_column(String(20))  # as typed: "DL 01 AB 1234"
    # Canonical form used for matching: "DL01AB1234". Indexed for fast gate lookups.
    plate_normalized: Mapped[str] = mapped_column(String(12), index=True)
    vehicle_type: Mapped[VehicleType] = mapped_column(str_enum(VehicleType, "vehicle_type"))
    make_model: Mapped[str | None] = mapped_column(String(60))  # "Maruti Swift"
    colour: Mapped[str | None] = mapped_column(String(30))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    flat: Mapped[Flat] = relationship(lazy="raise")


class WatchlistEntry(UUIDPrimaryKey, Timestamps, Base):
    """A flagged plate. Seeing it at a gate raises a high-priority alert."""

    __tablename__ = "watchlist"
    __table_args__ = (UniqueConstraint("society_id", "plate_normalized"),)

    society_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societies.id"))
    plate_normalized: Mapped[str] = mapped_column(String(12), index=True)
    reason: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    added_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
