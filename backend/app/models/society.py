import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Integer, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPrimaryKey

if TYPE_CHECKING:
    from app.models.user import Resident


class Society(UUIDPrimaryKey, Timestamps, Base):
    """A housing society. v1 runs one society, but every table keeps `society_id`
    so multi-society tenancy is possible later without reshaping the data."""

    __tablename__ = "societies"

    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")


class Flat(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "flats"
    __table_args__ = (UniqueConstraint("society_id", "block", "number"),)

    society_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societies.id"), index=True)
    block: Mapped[str] = mapped_column(String(8))  # "B"
    number: Mapped[str] = mapped_column(String(8))  # "402"
    floor: Mapped[int | None] = mapped_column(SmallInteger)
    # Visitor parking slots reserved for this flat (used by occupancy analytics later).
    parking_slots: Mapped[int] = mapped_column(SmallInteger, default=1)

    # Read-only: residents are added through the Resident model. Used to show who to call.
    residents: Mapped[list["Resident"]] = relationship(lazy="raise", viewonly=True)

    @property
    def label(self) -> str:
        """Human label used everywhere in the UI, e.g. "B-402"."""
        return f"{self.block}-{self.number}"


class SocietySettings(Timestamps, Base):
    """Settings the society's admin can change (Phase 4: visit time limits and the approval
    timeout). One row per society; when there is none, the defaults from app config apply."""

    __tablename__ = "society_settings"

    society_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societies.id"), primary_key=True)
    guest_minutes: Mapped[int] = mapped_column(Integer)
    delivery_minutes: Mapped[int] = mapped_column(Integer)
    cab_minutes: Mapped[int] = mapped_column(Integer)
    service_minutes: Mapped[int] = mapped_column(Integer)
    approval_timeout_seconds: Mapped[int] = mapped_column(Integer)
    # Visitors' personal data (and plate snapshots) are deleted after this many days.
    visitor_retention_days: Mapped[int] = mapped_column(Integer, server_default="90")
    # OCR reads below this confidence go to the guard review queue (Phase 6: admin-editable).
    plate_confidence_threshold: Mapped[float] = mapped_column(Float, server_default="0.8")
    # Parking spaces kept for visitors; the occupancy figure in analytics is measured against it.
    visitor_parking_slots: Mapped[int] = mapped_column(Integer, server_default="20")
