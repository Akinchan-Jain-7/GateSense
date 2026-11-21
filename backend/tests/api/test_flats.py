import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Flat, Society, User
from app.models.enums import UserRole
from tests.factories import auth_headers, make_flat, make_society, make_user, make_vehicle

URL = "/api/v1/flats"


async def test_admin_creates_a_flat_and_it_is_audited(
    client: httpx2.AsyncClient, admin: User, db: AsyncSession
) -> None:
    response = await client.post(
        URL, json={"block": "c", "number": "101", "floor": 1}, headers=auth_headers(admin)
    )

    assert response.status_code == 201
    body = response.json()
    assert body["label"] == "C-101"  # block is upper-cased
    assert body["parking_slots"] == 1
    log = await db.scalar(select(AuditLog).where(AuditLog.action == "flat.create"))
    assert log is not None
    assert log.actor_id == admin.id
    assert log.changes["number"] == "101"


async def test_duplicate_flat_is_a_conflict(
    client: httpx2.AsyncClient, admin: User, flat: Flat
) -> None:
    response = await client.post(
        URL, json={"block": "B", "number": "402"}, headers=auth_headers(admin)
    )

    assert response.status_code == 409
    assert "B-402 already exists" in response.json()["detail"]


async def test_unknown_fields_are_rejected(client: httpx2.AsyncClient, admin: User) -> None:
    response = await client.post(
        URL, json={"block": "B", "number": "1", "colour": "red"}, headers=auth_headers(admin)
    )

    assert response.status_code == 422


async def test_list_filters_searches_and_paginates(
    client: httpx2.AsyncClient, admin: User, db: AsyncSession, society: Society
) -> None:
    for block, number in [("A", "101"), ("A", "102"), ("B", "101"), ("B", "402")]:
        await make_flat(db, society, block, number)
    headers = auth_headers(admin)

    block_a = (await client.get(URL, params={"block": "a"}, headers=headers)).json()
    search = (await client.get(URL, params={"q": "b-4"}, headers=headers)).json()
    page_2 = (await client.get(URL, params={"limit": 3, "offset": 3}, headers=headers)).json()

    assert [f["label"] for f in block_a["items"]] == ["A-101", "A-102"]
    assert [f["label"] for f in search["items"]] == ["B-402"]
    assert page_2["total"] == 4
    assert page_2["limit"] == 3
    assert [f["label"] for f in page_2["items"]] == ["B-402"]


async def test_page_size_is_capped(client: httpx2.AsyncClient, admin: User) -> None:
    response = await client.get(URL, params={"limit": 10_000}, headers=auth_headers(admin))

    assert response.json()["limit"] == 100


async def test_guard_can_read_flats(client: httpx2.AsyncClient, guard: User, flat: Flat) -> None:
    response = await client.get(f"{URL}/{flat.id}", headers=auth_headers(guard))

    assert response.status_code == 200
    assert response.json()["label"] == "B-402"


async def test_update_flat(client: httpx2.AsyncClient, admin: User, flat: Flat) -> None:
    response = await client.patch(
        f"{URL}/{flat.id}", json={"parking_slots": 2, "floor": None}, headers=auth_headers(admin)
    )

    assert response.status_code == 200
    assert response.json()["parking_slots"] == 2
    assert response.json()["floor"] is None


async def test_update_rejects_null_for_required_fields(
    client: httpx2.AsyncClient, admin: User, flat: Flat
) -> None:
    response = await client.patch(
        f"{URL}/{flat.id}", json={"block": None}, headers=auth_headers(admin)
    )

    assert response.status_code == 422
    assert "cannot be null" in response.text


async def test_renaming_onto_an_existing_flat_is_a_conflict(
    client: httpx2.AsyncClient, admin: User, db: AsyncSession, society: Society, flat: Flat
) -> None:
    other = await make_flat(db, society, "B", "403")

    response = await client.patch(
        f"{URL}/{other.id}", json={"number": "402"}, headers=auth_headers(admin)
    )

    assert response.status_code == 409


async def test_delete_empty_flat(client: httpx2.AsyncClient, admin: User, flat: Flat) -> None:
    response = await client.delete(f"{URL}/{flat.id}", headers=auth_headers(admin))
    follow_up = await client.get(f"{URL}/{flat.id}", headers=auth_headers(admin))

    assert response.status_code == 204
    assert follow_up.status_code == 404


async def test_cannot_delete_a_flat_with_vehicles(
    client: httpx2.AsyncClient, admin: User, db: AsyncSession, society: Society, flat: Flat
) -> None:
    await make_vehicle(db, society, flat)

    response = await client.delete(f"{URL}/{flat.id}", headers=auth_headers(admin))

    assert response.status_code == 409
    assert "can't be deleted" in response.json()["detail"]


async def test_other_societies_are_invisible(
    client: httpx2.AsyncClient, admin: User, db: AsyncSession
) -> None:
    other_society = await make_society(db, "Other Society")
    other_flat = await make_flat(db, other_society, "Z", "101")
    other_admin = await make_user(db, other_society, UserRole.ADMIN, email="other@test.in")

    get = await client.get(f"{URL}/{other_flat.id}", headers=auth_headers(admin))
    patch = await client.patch(
        f"{URL}/{other_flat.id}", json={"floor": 2}, headers=auth_headers(admin)
    )
    listing = await client.get(URL, headers=auth_headers(other_admin))

    assert get.status_code == patch.status_code == 404
    assert [f["label"] for f in listing.json()["items"]] == ["Z-101"]
