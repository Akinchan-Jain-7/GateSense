import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.models.enums import ResidentType, UserRole, str_enum
from app.models.society import Flat


class User(UUIDPrimaryKey, Timestamps, Base):
    """Anyone who logs in: admin (society secretary), guard or resident."""

    __tablename__ = "users"

    society_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("societies.id"), index=True)
    # Stored lower-case; login looks users up by email.
    email: Mapped[str] = mapped_column(String(254), unique=True)
    full_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(20))
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole, "user_role"), index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # Users are deactivated, never deleted, so history (who approved what) stays intact.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Resident(UUIDPrimaryKey, Timestamps, Base):
    """Links a resident user to a flat. A person could live in (or own) several flats."""

    __tablename__ = "residents"
    __table_args__ = (UniqueConstraint("user_id", "flat_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    flat_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("flats.id"), index=True)
    resident_type: Mapped[ResidentType] = mapped_column(
        str_enum(ResidentType, "resident_type"), default=ResidentType.OWNER
    )
    # The first person asked to approve visitors for the flat.
    is_primary_contact: Mapped[bool] = mapped_column(Boolean, default=False)

    # lazy="raise": async code can't lazy-load, so we always load these explicitly
    # (selectinload / joinedload) and get a clear error if we forget.
    user: Mapped[User] = relationship(lazy="raise")
    flat: Mapped[Flat] = relationship(lazy="raise")


class RefreshToken(Timestamps, Base):
    """One row per issued refresh token, keyed by the token's `jti` claim.

    Storing them lets us rotate (each refresh token works once) and revoke on logout.
    """

    __tablename__ = "refresh_tokens"

    jti: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
