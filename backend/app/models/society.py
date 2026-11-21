import uuid

from sqlalchemy import ForeignKey, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey


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

    @property
    def label(self) -> str:
        """Human label used everywhere in the UI, e.g. "B-402"."""
        return f"{self.block}-{self.number}"
