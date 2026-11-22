"""Phase 6 backend additions: dashboard analytics, the audit log, demo mode and the new
admin settings (confidence threshold, visitor parking)."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.main import app
from app.models import Device, Flat, GateEvent, Society, User, Visit, Visitor, VisitStatusChange
from app.models.enums import LaneDirection, MatchResult, VisitCategory, VisitStatus, VisitTrigger
from app.services.analytics import IST
from tests import factories
from tests.api.test_gate_events import post_read
from tests.factories import auth_headers

NOW = datetime.now(UTC).replace(microsecond=0)
SOCIETY_IDS: dict[uuid.UUID, uuid.UUID] = {}  # gate id -> society id


def ago(**delta: float) -> datetime:
    return NOW - timedelta(**delta)


@pytest.fixture
def demo_mode() -> None:
    settings = get_settings().model_copy(update={"demo_mode": True})
    app.dependency_overrides[get_settings] = lambda: settings


async def overview(client: httpx2.AsyncClient, admin: User, days: int = 14) -> dict:  # type: ignore[type-arg]
    response = await client.get(
        f"/api/v1/analytics/overview?days={days}", headers=auth_headers(admin)
    )
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def add_visit(
    db: AsyncSession,
    society: Society,
    flat: Flat,
    visitor: Visitor,
    *,
    category: VisitCategory,
    status: VisitStatus,
    entered: datetime,
    exited: datetime | None = None,
    plate: str | None = None,
) -> Visit:
    visit = Visit(
        id=uuid.uuid4(),
        society_id=society.id,
        flat_id=flat.id,
        visitor_id=visitor.id,
        plate_normalized=plate,
        category=category,
        status=status,
        entered_at=entered,
        expected_exit_at=entered + timedelta(minutes=20),
        exited_at=exited,
    )
    db.add(visit)
    return visit


def add_read(
    db: AsyncSession, device: Device, plate: str, direction: LaneDirection, at: datetime
) -> GateEvent:
    event = GateEvent(
        id=uuid.uuid4(),
        society_id=SOCIETY_IDS[device.gate_id],
        gate_id=device.gate_id,
        device_id=device.id,
        direction=direction,
        plate_raw=plate,
        plate_normalized=plate,
        confidence=0.95,
        captured_at=at,
        event_hash=uuid.uuid4().hex,
        match_result=MatchResult.RESIDENT,
    )
    db.add(event)
    return event


async def test_overview_numbers_match_a_hand_built_scenario(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society, flat: Flat, admin: User
) -> None:
    regular = Visitor(society_id=society.id, full_name="Rahul Kumar", phone="+919876543210")
    once = Visitor(society_id=society.id, full_name="Sneha Gupta", phone="+919812345678")
    db.add_all([regular, once])
    await db.flush()
    # In the window: a 120-minute guest visit, a 30-minute delivery that overstayed, and a
    # cab that is inside right now. Outside the window: a visit from 20 days ago.
    add_visit(
        db,
        society,
        flat,
        regular,
        category=VisitCategory.GUEST,
        status=VisitStatus.EXITED,
        entered=ago(hours=3),
        exited=ago(hours=1),
    )
    late = add_visit(
        db,
        society,
        flat,
        once,
        category=VisitCategory.DELIVERY,
        status=VisitStatus.EXITED,
        entered=ago(hours=2),
        exited=ago(minutes=90),
    )
    add_visit(
        db,
        society,
        flat,
        regular,
        category=VisitCategory.CAB,
        status=VisitStatus.INSIDE,
        entered=ago(minutes=5),
        plate="DL1CAB1234",
    )
    add_visit(
        db,
        society,
        flat,
        once,
        category=VisitCategory.GUEST,
        status=VisitStatus.EXITED,
        entered=ago(days=20),
        exited=ago(days=20, hours=-1),
    )
    await db.flush()
    db.add(
        VisitStatusChange(
            visit_id=late.id,
            from_status=VisitStatus.INSIDE,
            to_status=VisitStatus.OVERSTAYED,
            trigger=VisitTrigger.OVERSTAY,
            changed_at=ago(minutes=100),
        )
    )
    # Resident cars: one came home (inside), one came home and left again (outside).
    gate = await factories.make_gate(db, society)
    entry, _ = await factories.make_device(db, gate, LaneDirection.ENTRY)
    exit_, _ = await factories.make_device(db, gate, LaneDirection.EXIT)
    SOCIETY_IDS[gate.id] = society.id
    home_at = ago(hours=4)
    add_read(db, entry, "UP16AB1234", LaneDirection.ENTRY, home_at)
    add_read(db, entry, "UP16CD5678", LaneDirection.ENTRY, ago(hours=6))
    add_read(db, exit_, "UP16CD5678", LaneDirection.EXIT, ago(hours=2))
    await db.commit()

    data = await overview(client, admin)
    inside = await client.get("/api/v1/analytics/inside", headers=auth_headers(admin))
    assert inside.json() == {
        "vehicles_inside": 2,
        "visitors_inside": 1,
        "residents_inside": 1,
        "visitor_vehicles_inside": 1,
        "visitor_parking_slots": 20,
    }

    assert data["visits"] == 3
    assert data["average_visit_minutes"] == 75.0  # (120 + 30) / 2
    assert (data["overstayed_visits"], data["overstay_rate"]) == (1, 0.3333)
    assert (data["visitors_inside"], data["visitor_vehicles_inside"]) == (1, 1)
    assert data["residents_inside"] == 1
    assert data["vehicles_inside"] == 2
    assert data["visitor_parking_slots"] == 20

    hours = {h["hour"]: h for h in data["busiest_hours"]}
    assert len(hours) == 24
    assert hours[home_at.astimezone(IST).hour]["residents"] >= 1
    assert sum(h["residents"] for h in hours.values()) == 2  # entry lane only
    assert sum(d["visits"] for d in data["daily_visits"]) == 3
    assert len(data["daily_visits"]) in (15, 16)  # every day in the window, quiet ones too

    categories = {c["category"]: c for c in data["categories"]}
    assert categories["guest"] == {"category": "guest", "visits": 1, "average_minutes": 120.0}
    assert categories["service"] == {"category": "service", "visits": 0, "average_minutes": None}

    top = data["frequent_visitors"][0]
    assert (top["name"], top["visits"], top["flats"]) == ("Rahul Kumar", 2, [flat.label])
    assert top["phone_masked"] == "+91 98•••••210"


async def test_overview_with_no_data_has_no_rate(client: httpx2.AsyncClient, admin: User) -> None:
    data = await overview(client, admin, days=7)
    assert (data["visits"], data["overstay_rate"], data["average_visit_minutes"]) == (0, None, None)
    assert data["frequent_visitors"] == []


async def test_analytics_and_audit_are_admin_only(
    client: httpx2.AsyncClient, guard: User, resident: User
) -> None:
    for user in (guard, resident):
        for url in ("/api/v1/analytics/overview", "/api/v1/audit-logs"):
            response = await client.get(url, headers=auth_headers(user))
            assert response.status_code == 403, url


async def test_window_must_be_1_to_90_days(client: httpx2.AsyncClient, admin: User) -> None:
    for days in (0, 91):
        response = await client.get(
            f"/api/v1/analytics/overview?days={days}", headers=auth_headers(admin)
        )
        assert response.status_code == 422


async def test_audit_log_lists_admin_changes(client: httpx2.AsyncClient, admin: User) -> None:
    headers = auth_headers(admin)
    created = await client.post(
        "/api/v1/flats", json={"block": "E", "number": "101", "floor": 1}, headers=headers
    )
    assert created.status_code == 201, created.text
    await client.patch("/api/v1/settings/visits", json={"cab_minutes": 15}, headers=headers)

    entries = (await client.get("/api/v1/audit-logs", headers=headers)).json()
    # Both changes share one test transaction (same timestamp), so compare without order.
    by_action = {e["action"]: e for e in entries["items"]}
    assert set(by_action) == {"settings.update", "flat.create"}
    assert by_action["flat.create"]["entity_id"] == created.json()["id"]
    assert by_action["flat.create"]["actor"]["full_name"] == admin.full_name

    flats_only = await client.get("/api/v1/audit-logs?entity_type=flat", headers=headers)
    assert flats_only.json()["total"] == 1
    by_someone_else = await client.get(
        f"/api/v1/audit-logs?actor_id={uuid.uuid4()}", headers=headers
    )
    assert by_someone_else.json()["total"] == 0


async def test_admin_can_raise_the_confidence_threshold(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society, flat: Flat, admin: User
) -> None:
    gate = await factories.make_gate(db, society)
    _, key = await factories.make_device(db, gate, LaneDirection.ENTRY)
    await factories.make_vehicle(db, society, flat, "UP16AB1234")
    first = (await post_read(client, key, "UP16AB1234", confidence=0.85)).json()["event"]
    assert first["match_result"] == "resident"  # 0.85 is above the default 0.80

    response = await client.patch(
        "/api/v1/settings/visits",
        json={"plate_confidence_threshold": 0.9, "visitor_parking_slots": 35},
        headers=auth_headers(admin),
    )
    assert response.status_code == 200
    assert response.json()["plate_confidence_threshold"] == 0.9

    later = datetime.now(UTC) - timedelta(minutes=1)
    second = (await post_read(client, key, "UP16AB1234", confidence=0.85, at=later)).json()
    assert second["event"]["needs_review"] is True
    assert (await overview(client, admin))["visitor_parking_slots"] == 35


async def test_settings_reject_silly_thresholds(client: httpx2.AsyncClient, admin: User) -> None:
    for value in (0.1, 1.0):
        response = await client.patch(
            "/api/v1/settings/visits",
            json={"plate_confidence_threshold": value},
            headers=auth_headers(admin),
        )
        assert response.status_code == 422


async def test_demo_info_is_empty_when_demo_mode_is_off(client: httpx2.AsyncClient) -> None:
    assert (await client.get("/api/v1/demo")).json() == {
        "enabled": False,
        "password": None,
        "accounts": [],
    }


async def test_reset_is_hidden_when_demo_mode_is_off(
    client: httpx2.AsyncClient, admin: User
) -> None:
    response = await client.post("/api/v1/demo/reset", headers=auth_headers(admin))
    assert response.status_code == 404


async def test_demo_info_lists_the_three_roles(client: httpx2.AsyncClient, demo_mode: None) -> None:
    info = (await client.get("/api/v1/demo")).json()
    assert info["enabled"] is True
    assert info["password"] == get_settings().demo_password
    assert [a["role"] for a in info["accounts"]] == ["guard", "resident", "admin"]


async def test_reset_reseeds_with_history_and_signs_everyone_out(
    client: httpx2.AsyncClient, db: AsyncSession, admin: User, guard: User, demo_mode: None
) -> None:
    assert (await client.post("/api/v1/demo/reset", headers=auth_headers(guard))).status_code == 403

    response = await client.post("/api/v1/demo/reset", headers=auth_headers(admin))

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["flats"], body["residents"]) == (40, 60)
    assert body["history_visits"] > 100
    assert await db.scalar(select(func.count()).select_from(Visit)) >= body["history_visits"]
    # The old admin no longer exists, so the old token is useless.
    assert (await client.get("/api/v1/me", headers=auth_headers(admin))).status_code == 401
