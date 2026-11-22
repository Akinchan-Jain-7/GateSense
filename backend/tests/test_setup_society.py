"""The first-admin command for self-hosted (non-demo) deployments."""

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_password
from app.models import User
from app.models.enums import UserRole
from app.setup_society import AlreadySetUpError, setup
from tests import factories


async def test_creates_the_society_and_its_admin(db: AsyncSession) -> None:
    created = await setup(
        db,
        society="Aravali Heights",
        address="Sector 150, Noida",
        name="Anil Mehta",
        email="Secretary@Example.org",
        password="a-long-passphrase",
    )
    admin = await db.scalar(select(User).where(User.id == created.admin.id))
    assert admin is not None
    assert admin.role is UserRole.ADMIN
    assert admin.email == "secretary@example.org"
    assert verify_password("a-long-passphrase", admin.password_hash)


async def test_refuses_a_database_that_is_already_set_up(db: AsyncSession) -> None:
    await factories.make_society(db)
    with pytest.raises(AlreadySetUpError):
        await setup(
            db, society="X", address=None, name="Y", email="y@example.org", password="p" * 8
        )


async def test_rejects_a_short_password(db: AsyncSession) -> None:
    with pytest.raises(ValidationError):
        await setup(
            db, society="X", address=None, name="Y", email="y@example.org", password="short"
        )
