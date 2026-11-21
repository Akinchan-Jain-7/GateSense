import httpx2
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Device, Flat, Resident, User, Vehicle
from app.models.enums import UserRole
from app.seed import (
    DEMO_ADMIN_EMAIL,
    DEMO_GUARD_EMAIL,
    DEMO_RESIDENT_EMAIL,
    is_seeded,
    reset_database,
    seed,
)
from app.services.plates import is_valid_plate


async def count(db: AsyncSession, model: type[object]) -> int:
    return await db.scalar(select(func.count()).select_from(model)) or 0


async def test_seed_creates_realistic_demo_data(db: AsyncSession) -> None:
    assert not await is_seeded(db)

    summary = await seed(db, get_settings())

    assert await is_seeded(db)
    assert summary.flats == await count(db, Flat) == 40
    assert summary.residents == await count(db, Resident) == 60
    assert 75 <= summary.vehicles == await count(db, Vehicle) <= 85
    assert summary.devices == await count(db, Device) == 4
    guards = await db.scalar(select(func.count()).where(User.role == UserRole.GUARD))
    assert guards == summary.guards == 3
    plates = (await db.scalars(select(Vehicle.plate_normalized))).all()
    assert all(is_valid_plate(plate) for plate in plates)
    assert len(summary.device_keys) == 4


async def test_demo_logins_work(client: httpx2.AsyncClient, db: AsyncSession) -> None:
    settings = get_settings()
    await seed(db, settings)

    for email in (DEMO_ADMIN_EMAIL, DEMO_GUARD_EMAIL, DEMO_RESIDENT_EMAIL):
        response = await client.post(
            "/api/v1/auth/login", data={"username": email, "password": settings.demo_password}
        )
        assert response.status_code == 200, email

    token = (
        await client.post(
            "/api/v1/auth/login",
            data={"username": DEMO_RESIDENT_EMAIL, "password": settings.demo_password},
        )
    ).json()["access_token"]
    me = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["full_name"] == "Priya Sharma"
    assert [flat["label"] for flat in me.json()["flats"]] == ["B-402"]


async def test_seed_is_deterministic_and_reset_empties_everything(db: AsyncSession) -> None:
    first = await seed(db, get_settings())
    first_plates = sorted((await db.scalars(select(Vehicle.plate_normalized))).all())

    await reset_database(db)
    assert not await is_seeded(db)
    second = await seed(db, get_settings())
    second_plates = sorted((await db.scalars(select(Vehicle.plate_normalized))).all())

    assert first.vehicles == second.vehicles
    assert first_plates == second_plates
