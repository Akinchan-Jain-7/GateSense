import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Flat, Society, User
from tests.factories import auth_headers, make_flat, make_vehicle

URL = "/api/v1/vehicles"


async def test_create_vehicle_normalizes_the_plate(
    client: httpx2.AsyncClient, admin: User, flat: Flat
) -> None:
    response = await client.post(
        URL,
        json={
            "flat_id": str(flat.id),
            "plate": "up16 ab-1234",
            "vehicle_type": "car",
            "make_model": "Tata Nexon",
            "colour": "Grey",
        },
        headers=auth_headers(admin),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["plate_raw"] == "up16 ab-1234"
    assert body["plate_normalized"] == "UP16AB1234"
    assert body["flat"]["label"] == "B-402"


async def test_invalid_plate_is_422(client: httpx2.AsyncClient, admin: User, flat: Flat) -> None:
    response = await client.post(
        URL,
        json={"flat_id": str(flat.id), "plate": "HELLO123", "vehicle_type": "car"},
        headers=auth_headers(admin),
    )

    assert response.status_code == 422
    assert "not a valid Indian number plate" in response.json()["detail"]


async def test_same_plate_twice_is_a_conflict_even_if_typed_differently(
    client: httpx2.AsyncClient, admin: User, db: AsyncSession, society: Society, flat: Flat
) -> None:
    await make_vehicle(db, society, flat, "UP16AB1234")

    response = await client.post(
        URL,
        json={"flat_id": str(flat.id), "plate": "UP 16 AB 1234", "vehicle_type": "two_wheeler"},
        headers=auth_headers(admin),
    )

    assert response.status_code == 409


async def test_guard_searches_by_partial_plate(
    client: httpx2.AsyncClient, guard: User, db: AsyncSession, society: Society, flat: Flat
) -> None:
    await make_vehicle(db, society, flat, "UP16AB1234")
    await make_vehicle(db, society, flat, "DL3CXY9876")

    response = await client.get(URL, params={"q": "ab 12"}, headers=auth_headers(guard))

    assert [v["plate_normalized"] for v in response.json()["items"]] == ["UP16AB1234"]


async def test_list_filters_by_flat_type_and_active(
    client: httpx2.AsyncClient, admin: User, db: AsyncSession, society: Society, flat: Flat
) -> None:
    other_flat = await make_flat(db, society, "A", "101")
    await make_vehicle(db, society, flat, "UP16AB1234")
    parked = await make_vehicle(db, society, other_flat, "UP16CD5678")
    parked.is_active = False
    await db.commit()
    headers = auth_headers(admin)

    by_flat = (await client.get(URL, params={"flat_id": str(flat.id)}, headers=headers)).json()
    inactive = (await client.get(URL, params={"is_active": False}, headers=headers)).json()
    bikes = (await client.get(URL, params={"vehicle_type": "two_wheeler"}, headers=headers)).json()

    assert [v["plate_normalized"] for v in by_flat["items"]] == ["UP16AB1234"]
    assert [v["plate_normalized"] for v in inactive["items"]] == ["UP16CD5678"]
    assert bikes["total"] == 0


async def test_update_plate_and_move_to_another_flat(
    client: httpx2.AsyncClient, admin: User, db: AsyncSession, society: Society, flat: Flat
) -> None:
    vehicle = await make_vehicle(db, society, flat, "UP16AB1234")
    new_flat = await make_flat(db, society, "D", "501")

    response = await client.patch(
        f"{URL}/{vehicle.id}",
        json={"plate": "UP16 AB 4321", "flat_id": str(new_flat.id), "colour": None},
        headers=auth_headers(admin),
    )

    assert response.status_code == 200
    assert response.json()["plate_normalized"] == "UP16AB4321"
    assert response.json()["flat"]["label"] == "D-501"
    log = await db.scalar(select(AuditLog).where(AuditLog.action == "vehicle.update"))
    assert log is not None
    assert log.changes["plate_normalized"] == ["UP16AB1234", "UP16AB4321"]


async def test_update_onto_an_existing_plate_is_a_conflict(
    client: httpx2.AsyncClient, admin: User, db: AsyncSession, society: Society, flat: Flat
) -> None:
    await make_vehicle(db, society, flat, "UP16AB1234")
    second = await make_vehicle(db, society, flat, "UP16CD5678")

    response = await client.patch(
        f"{URL}/{second.id}", json={"plate": "UP16AB1234"}, headers=auth_headers(admin)
    )

    assert response.status_code == 409


async def test_delete_vehicle(
    client: httpx2.AsyncClient, admin: User, db: AsyncSession, society: Society, flat: Flat
) -> None:
    vehicle = await make_vehicle(db, society, flat)

    response = await client.delete(f"{URL}/{vehicle.id}", headers=auth_headers(admin))
    follow_up = await client.get(f"{URL}/{vehicle.id}", headers=auth_headers(admin))

    assert response.status_code == 204
    assert follow_up.status_code == 404
