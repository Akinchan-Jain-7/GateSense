"""Guest passes (plate and code) and admin-configurable visit settings."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Flat, GuestPass, Resident, Society, User, Visit
from app.models.enums import LaneDirection, VisitStatus
from tests import factories
from tests.factories import auth_headers

PASSES = "/api/v1/guest-passes"


def window(hours_from: float = -1, hours_until: float = 5) -> dict[str, str]:
    now = datetime.now(UTC)
    return {
        "valid_from": (now + timedelta(hours=hours_from)).isoformat(),
        "valid_until": (now + timedelta(hours=hours_until)).isoformat(),
    }


async def create_pass(client: httpx2.AsyncClient, resident: User, **fields: Any) -> dict[str, Any]:
    body = {"guest_name": "Priya Nair", "guest_phone": "9988776655", **window(), **fields}
    response = await client.post(PASSES, json=body, headers=auth_headers(resident))
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


@pytest.fixture
async def entry_key(db: AsyncSession, society: Society) -> str:
    gate = await factories.make_gate(db, society)
    _, key = await factories.make_device(db, gate, LaneDirection.ENTRY)
    return key


async def camera(
    client: httpx2.AsyncClient, key: str, plate: str, minutes_ago: float = 1
) -> dict[str, Any]:
    at = (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()
    response = await client.post(
        "/api/v1/gate-events",
        data={"plate_text": plate, "confidence": "0.95", "captured_at": at},
        headers={"X-Device-Key": key},
    )
    event: dict[str, Any] = response.json()["event"]
    return event


async def test_plate_pass_lets_the_car_in_without_asking(
    client: httpx2.AsyncClient, resident: User, entry_key: str, db: AsyncSession
) -> None:
    created = await create_pass(client, resident, plate="KA 05 MN 0042", max_uses=2)
    assert created["code"] is None
    assert created["guest_pass"]["guest_phone"] == "+91 99•••••655"

    event = await camera(client, entry_key, "KAO5MN0042")  # OCR look-alike repaired first
    assert event["match_result"] == "guest_pass"
    visit = await db.get(Visit, uuid.UUID(event["visit_id"]))
    assert visit is not None
    assert visit.status is VisitStatus.INSIDE
    assert str(visit.guest_pass_id) == created["guest_pass"]["id"]
    assert visit.approved_by_id == resident.id
    guest_pass = await db.get(GuestPass, uuid.UUID(created["guest_pass"]["id"]))
    await db.refresh(guest_pass)
    assert guest_pass is not None and guest_pass.use_count == 1


async def test_used_up_expired_and_revoked_passes_dont_match(
    client: httpx2.AsyncClient, resident: User, entry_key: str
) -> None:
    await create_pass(client, resident, plate="KA05MN0042", max_uses=1)
    later = await create_pass(
        client, resident, plate="DL01AB1234", **window(hours_from=2, hours_until=6)
    )
    revoked = await create_pass(client, resident, plate="HR26DK8337")
    response = await client.post(
        f"{PASSES}/{revoked['guest_pass']['id']}/revoke", headers=auth_headers(resident)
    )
    assert response.json()["revoked_at"] is not None

    assert (await camera(client, entry_key, "KA05MN0042", minutes_ago=10))[
        "match_result"
    ] == "guest_pass"
    assert (await camera(client, entry_key, "KA05MN0042", minutes_ago=2))[
        "match_result"
    ] == "unknown"  # used up
    assert (await camera(client, entry_key, "DL01AB1234"))[
        "match_result"
    ] == "unknown"  # not valid yet
    assert (await camera(client, entry_key, "HR26DK8337"))["match_result"] == "unknown"  # revoked
    assert later["guest_pass"]["use_count"] == 0


async def test_code_pass_is_shown_once_and_redeemed_by_the_guard(
    client: httpx2.AsyncClient, resident: User, guard: User, db: AsyncSession
) -> None:
    created = await create_pass(client, resident, with_code=True, category="delivery")
    code = created["code"]
    assert code and len(code) == 8 and not set(code) & set("ILO01")
    stored = await db.get(GuestPass, uuid.UUID(created["guest_pass"]["id"]))
    assert stored is not None and stored.code_hash and code not in stored.code_hash  # only an HMAC

    listed = (await client.get(PASSES, headers=auth_headers(resident))).json()
    assert listed["items"][0]["has_code"] is True
    assert "code" not in listed["items"][0]

    redeemed = await client.post(
        f"{PASSES}/redeem",
        json={"code": code.lower(), "plate": "UP14FT4410"},
        headers=auth_headers(guard),
    )
    assert redeemed.status_code == 201
    assert (redeemed.json()["status"], redeemed.json()["plate_normalized"]) == (
        "inside",
        "UP14FT4410",
    )
    again = await client.post(f"{PASSES}/redeem", json={"code": code}, headers=auth_headers(guard))
    assert again.status_code == 409  # one use
    wrong = await client.post(
        f"{PASSES}/redeem", json={"code": "ZZZZZZZZ"}, headers=auth_headers(guard)
    )
    assert wrong.status_code == 404


@pytest.mark.parametrize(
    "fields",
    [
        {"plate": None, "with_code": False},  # neither plate nor code
        {**window(hours_from=1, hours_until=0)},  # ends before it starts
        {**window(hours_from=-1, hours_until=24 * 40)},  # longer than 30 days
        {"plate": "KA05MN0042", "max_uses": 0},
        {"plate": "KA05MN0042", "guest_phone": "123"},
    ],
)
async def test_bad_passes_are_rejected(
    client: httpx2.AsyncClient, resident: User, fields: dict[str, Any]
) -> None:
    body = {"guest_name": "Priya Nair", **window(), **fields}
    response = await client.post(PASSES, json=body, headers=auth_headers(resident))
    assert response.status_code == 422


async def test_pass_in_the_past_is_rejected(client: httpx2.AsyncClient, resident: User) -> None:
    body = {
        "guest_name": "Priya Nair",
        "plate": "KA05MN0042",
        **window(hours_from=-5, hours_until=-1),
    }
    assert (await client.post(PASSES, json=body, headers=auth_headers(resident))).status_code == 422


async def test_residents_only_see_and_revoke_their_own_passes(
    client: httpx2.AsyncClient, resident: User, guard: User, society: Society, db: AsyncSession
) -> None:
    mine = await create_pass(client, resident, plate="KA05MN0042")
    other_flat = await factories.make_flat(db, society, "C", "104")
    neighbour = await factories.make_resident(db, society, other_flat, email="neighbour@test.in")
    assert (await client.get(PASSES, headers=auth_headers(neighbour))).json()["total"] == 0
    response = await client.post(
        f"{PASSES}/{mine['guest_pass']['id']}/revoke", headers=auth_headers(neighbour)
    )
    assert response.status_code == 404
    assert (await client.get(PASSES, headers=auth_headers(guard))).json()["total"] == 1
    assert (await client.get(f"{PASSES}?active=true", headers=auth_headers(guard))).json()[
        "total"
    ] == 1


async def test_multi_flat_residents_must_pick_a_flat(
    client: httpx2.AsyncClient, resident: User, society: Society, db: AsyncSession, flat: Flat
) -> None:
    second = await factories.make_flat(db, society, "D", "201")
    db.add(Resident(user_id=resident.id, flat_id=second.id))
    await db.commit()
    body = {"guest_name": "Priya Nair", "plate": "KA05MN0042", **window()}
    assert (await client.post(PASSES, json=body, headers=auth_headers(resident))).status_code == 422
    ok = await client.post(
        PASSES, json={**body, "flat_id": str(second.id)}, headers=auth_headers(resident)
    )
    assert ok.json()["guest_pass"]["flat_id"] == str(second.id)


# --- Settings ----------------------------------------------------------------------------


async def test_visit_settings_defaults_and_admin_update(
    client: httpx2.AsyncClient, admin: User, guard: User, db: AsyncSession
) -> None:
    defaults = (await client.get("/api/v1/settings/visits", headers=auth_headers(guard))).json()
    assert defaults == {
        "guest_minutes": 240,
        "delivery_minutes": 20,
        "cab_minutes": 10,
        "service_minutes": 120,
        "approval_timeout_seconds": 180,
        "visitor_retention_days": 90,
    }
    updated = await client.patch(
        "/api/v1/settings/visits",
        json={"delivery_minutes": 30, "approval_timeout_seconds": 120},
        headers=auth_headers(admin),
    )
    assert updated.json()["delivery_minutes"] == 30
    assert updated.json()["guest_minutes"] == 240
    log = await db.scalar(select(AuditLog).where(AuditLog.action == "settings.update"))
    assert log is not None
    assert log.changes == {
        "delivery_minutes": {"from": 20, "to": 30},
        "approval_timeout_seconds": {"from": 180, "to": 120},
    }
    bad = await client.patch(
        "/api/v1/settings/visits", json={"cab_minutes": 0}, headers=auth_headers(admin)
    )
    assert bad.status_code == 422


async def test_new_limits_apply_to_visits(
    client: httpx2.AsyncClient, admin: User, guard: User, resident: User, flat: Flat
) -> None:
    await client.patch(
        "/api/v1/settings/visits",
        json={"cab_minutes": 15, "approval_timeout_seconds": 60},
        headers=auth_headers(admin),
    )
    registered = await client.post(
        "/api/v1/visits",
        json={
            "full_name": "Uber driver",
            "phone": "9000000001",
            "flat_id": str(flat.id),
            "category": "cab",
        },
        headers=auth_headers(guard),
    )
    approval = registered.json()["approval"]
    waited = datetime.fromisoformat(approval["expires_at"]) - datetime.fromisoformat(
        approval["requested_at"]
    )
    assert waited == timedelta(seconds=60)
    await client.post(
        f"/api/v1/approvals/{approval['id']}/decision",
        json={"decision": "approve"},
        headers=auth_headers(resident),
    )
    entered = (
        await client.post(
            f"/api/v1/visits/{registered.json()['visit']['id']}/enter", headers=auth_headers(guard)
        )
    ).json()
    assert datetime.fromisoformat(entered["expected_exit_at"]) - datetime.fromisoformat(
        entered["entered_at"]
    ) == timedelta(minutes=15)
