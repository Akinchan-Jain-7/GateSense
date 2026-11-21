from datetime import UTC, datetime

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GateEvent, Society, User
from app.models.enums import LaneDirection, MatchResult
from tests.factories import auth_headers, make_device, make_gate

GATES, DEVICES = "/api/v1/gates", "/api/v1/devices"


async def test_gate_crud(client: httpx2.AsyncClient, admin: User) -> None:
    headers = auth_headers(admin)

    created = await client.post(
        GATES, json={"name": "Main Gate", "location": "Sector 150 road"}, headers=headers
    )
    gate_id = created.json()["id"]
    updated = await client.patch(f"{GATES}/{gate_id}", json={"location": None}, headers=headers)
    listed = await client.get(GATES, params={"is_active": True}, headers=headers)
    fetched = await client.get(f"{GATES}/{gate_id}", headers=headers)
    deleted = await client.delete(f"{GATES}/{gate_id}", headers=headers)

    assert created.status_code == 201
    assert updated.json()["location"] is None
    assert listed.json()["total"] == 1
    assert fetched.json()["name"] == "Main Gate"
    assert deleted.status_code == 204


async def test_gate_with_devices_cannot_be_deleted(
    client: httpx2.AsyncClient, admin: User, db: AsyncSession, society: Society
) -> None:
    gate = await make_gate(db, society)
    await make_device(db, gate)

    response = await client.delete(f"{GATES}/{gate.id}", headers=auth_headers(admin))

    assert response.status_code == 409
    assert "deactivate it instead" in response.json()["detail"]


async def test_create_device_returns_the_key_once(
    client: httpx2.AsyncClient, admin: User, db: AsyncSession, society: Society
) -> None:
    gate = await make_gate(db, society)
    headers = auth_headers(admin)

    created = await client.post(
        DEVICES,
        json={"gate_id": str(gate.id), "name": "Main entry cam", "direction": "entry"},
        headers=headers,
    )
    fetched = await client.get(f"{DEVICES}/{created.json()['id']}", headers=headers)

    assert created.status_code == 201
    api_key = created.json()["api_key"]
    assert api_key.startswith(created.json()["api_key_prefix"])
    assert "api_key" not in fetched.json()  # never shown again
    me = await client.get(f"{DEVICES}/me", headers={"X-Device-Key": api_key})
    assert me.status_code == 200
    assert me.json()["direction"] == "entry"


async def test_device_for_unknown_gate_is_404(client: httpx2.AsyncClient, admin: User) -> None:
    response = await client.post(
        DEVICES,
        json={
            "gate_id": "00000000-0000-0000-0000-000000000000",
            "name": "Cam",
            "direction": "exit",
        },
        headers=auth_headers(admin),
    )

    assert response.status_code == 404


async def test_device_key_auth(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society
) -> None:
    gate = await make_gate(db, society)
    device, api_key = await make_device(db, gate)

    ok = await client.get(f"{DEVICES}/me", headers={"X-Device-Key": api_key})
    wrong = await client.get(f"{DEVICES}/me", headers={"X-Device-Key": "gsd_wrong"})
    missing = await client.get(f"{DEVICES}/me")

    assert ok.status_code == 200
    assert ok.json()["id"] == str(device.id)
    assert wrong.status_code == missing.status_code == 401
    await db.refresh(device)
    assert device.last_seen_at is not None


async def test_inactive_device_or_gate_cannot_authenticate(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society
) -> None:
    gate = await make_gate(db, society)
    device, api_key = await make_device(db, gate)
    other_gate = await make_gate(db, society, "Service Gate")
    _, other_key = await make_device(db, other_gate)
    device.is_active = False
    other_gate.is_active = False
    await db.commit()

    first = await client.get(f"{DEVICES}/me", headers={"X-Device-Key": api_key})
    second = await client.get(f"{DEVICES}/me", headers={"X-Device-Key": other_key})

    assert first.status_code == second.status_code == 401


async def test_rotating_a_key_invalidates_the_old_one(
    client: httpx2.AsyncClient, admin: User, db: AsyncSession, society: Society
) -> None:
    gate = await make_gate(db, society)
    device, old_key = await make_device(db, gate)

    rotated = await client.post(f"{DEVICES}/{device.id}/rotate-key", headers=auth_headers(admin))
    new_key = rotated.json()["api_key"]

    assert new_key != old_key
    assert (await client.get(f"{DEVICES}/me", headers={"X-Device-Key": old_key})).status_code == 401
    assert (await client.get(f"{DEVICES}/me", headers={"X-Device-Key": new_key})).status_code == 200


async def test_device_list_filters_and_update(
    client: httpx2.AsyncClient, admin: User, db: AsyncSession, society: Society
) -> None:
    gate = await make_gate(db, society)
    entry, _ = await make_device(db, gate, LaneDirection.ENTRY)
    await make_device(db, gate, LaneDirection.EXIT)
    headers = auth_headers(admin)

    exits = (await client.get(DEVICES, params={"direction": "exit"}, headers=headers)).json()
    by_gate = (await client.get(DEVICES, params={"gate_id": str(gate.id)}, headers=headers)).json()
    updated = await client.patch(
        f"{DEVICES}/{entry.id}", json={"is_active": False}, headers=headers
    )
    inactive = (await client.get(DEVICES, params={"is_active": False}, headers=headers)).json()

    assert exits["total"] == 1
    assert by_gate["total"] == 2
    assert updated.json()["is_active"] is False
    assert [d["id"] for d in inactive["items"]] == [str(entry.id)]


async def test_device_with_events_cannot_be_deleted(
    client: httpx2.AsyncClient, admin: User, db: AsyncSession, society: Society
) -> None:
    gate = await make_gate(db, society)
    device, _ = await make_device(db, gate)
    unused, _ = await make_device(db, gate, LaneDirection.EXIT)
    db.add(
        GateEvent(
            society_id=society.id,
            gate_id=gate.id,
            device_id=device.id,
            direction=LaneDirection.ENTRY,
            plate_raw="UP16AB1234",
            confidence=0.93,
            captured_at=datetime.now(UTC),
            event_hash="test-hash",
            match_result=MatchResult.UNKNOWN,
        )
    )
    await db.commit()
    headers = auth_headers(admin)

    blocked = await client.delete(f"{DEVICES}/{device.id}", headers=headers)
    allowed = await client.delete(f"{DEVICES}/{unused.id}", headers=headers)

    assert blocked.status_code == 409
    assert allowed.status_code == 204


async def test_devices_of_other_societies_are_invisible(
    client: httpx2.AsyncClient, admin: User, db: AsyncSession
) -> None:
    other = Society(name="Elsewhere")
    db.add(other)
    await db.commit()
    gate = await make_gate(db, other)
    device, _ = await make_device(db, gate)

    response = await client.get(f"{DEVICES}/{device.id}", headers=auth_headers(admin))

    assert response.status_code == 404
