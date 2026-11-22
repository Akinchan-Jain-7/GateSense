from datetime import UTC, datetime, timedelta

import httpx2
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Device, Flat, GateEvent, ReconciliationFlag, Resident, User, Vehicle, Visit
from app.models.enums import LaneDirection, MatchResult, UserRole, VisitStatus
from app.seed import (
    DEMO_ADMIN_EMAIL,
    DEMO_GUARD_EMAIL,
    DEMO_RESIDENT_EMAIL,
    is_seeded,
    reset_database,
    seed,
)
from app.services import analytics, reconciliation
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


async def test_history_is_closed_consistent_and_feeds_the_dashboard(db: AsyncSession) -> None:
    settings = get_settings()
    now = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)  # 5:30 pm IST

    summary = await seed(db, settings, history_days=7, now=now)

    visits = (await db.scalars(select(Visit))).all()
    assert len([v for v in visits if v.entered_at]) == summary.history_visits > 50
    # Every visit is over, so nothing escalates or emails anyone when the demo starts.
    assert {v.status for v in visits} <= {VisitStatus.EXITED, VisitStatus.DENIED}
    assert all(v.exited_at is None or v.exited_at <= now for v in visits)
    assert all(v.entered_at < v.exited_at for v in visits if v.entered_at and v.exited_at)

    events = (await db.scalars(select(GateEvent).order_by(GateEvent.captured_at))).all()
    assert len(events) == summary.history_gate_events
    assert all(is_valid_plate(e.plate_normalized or "") for e in events)
    # Resident cars alternate in, out, in, ...: reconciliation has nothing to flag.
    by_plate: dict[str, list[LaneDirection]] = {}
    for event in events:
        if event.match_result == MatchResult.RESIDENT:
            by_plate.setdefault(event.plate_normalized or "", []).append(event.direction)
    for directions in by_plate.values():
        assert directions[0] == LaneDirection.ENTRY
        assert all(a != b for a, b in zip(directions, directions[1:], strict=False))
    society_id = visits[0].society_id
    await reconciliation.reconcile(db, settings, now=now + timedelta(hours=2))
    assert await count(db, ReconciliationFlag) == 0

    # 8 days: the history starts at midnight IST 7 days back, a 7-day window mid-afternoon.
    data = await analytics.overview(db, settings, society_id, now=now, days=8)
    assert data.visits == summary.history_visits
    assert 0 < data.overstayed_visits < data.visits
    assert data.visitors_inside == 0
    assert sum(h.residents + h.visitors for h in data.busiest_hours) > 0


async def test_history_is_the_same_every_run(db: AsyncSession) -> None:
    now = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    first = await seed(db, get_settings(), history_days=3, now=now)
    await reset_database(db)
    second = await seed(db, get_settings(), history_days=3, now=now)
    assert (first.history_visits, first.history_gate_events) == (
        second.history_visits,
        second.history_gate_events,
    )
