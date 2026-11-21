import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Flat, RefreshToken, Resident, Society, User
from tests.factories import TEST_PASSWORD, auth_headers, make_flat, make_resident

URL = "/api/v1/residents"


def new_resident(flat: Flat, **overrides: object) -> dict[str, object]:
    return {
        "flat_id": str(flat.id),
        "full_name": "Rohan Kapoor",
        "email": "Rohan.Kapoor@Example.com",
        "phone": "98765 43210",
        "password": "a-long-password",
        **overrides,
    }


async def test_create_resident_creates_a_login(
    client: httpx2.AsyncClient, admin: User, flat: Flat, db: AsyncSession
) -> None:
    response = await client.post(URL, json=new_resident(flat), headers=auth_headers(admin))

    assert response.status_code == 201
    body = response.json()
    assert body["flat"] == {"id": str(flat.id), "label": "B-402"}
    assert body["user"]["email"] == "rohan.kapoor@example.com"
    assert body["user"]["phone"] == "+919876543210"
    assert body["resident_type"] == "owner"
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": "rohan.kapoor@example.com", "password": "a-long-password"},
    )
    assert login.status_code == 200
    log = await db.scalar(select(AuditLog).where(AuditLog.action == "resident.create"))
    assert log is not None
    assert "password" not in log.changes


async def test_invalid_phone_and_short_password_are_rejected(
    client: httpx2.AsyncClient, admin: User, flat: Flat
) -> None:
    bad_phone = await client.post(
        URL, json=new_resident(flat, phone="12345"), headers=auth_headers(admin)
    )
    short_password = await client.post(
        URL, json=new_resident(flat, password="short"), headers=auth_headers(admin)
    )

    assert bad_phone.status_code == short_password.status_code == 422


async def test_duplicate_email_is_a_conflict(
    client: httpx2.AsyncClient, admin: User, flat: Flat, resident: User
) -> None:
    response = await client.post(
        URL, json=new_resident(flat, email="resident@test.in"), headers=auth_headers(admin)
    )

    assert response.status_code == 409


async def test_unknown_flat_is_404(client: httpx2.AsyncClient, admin: User, flat: Flat) -> None:
    payload = new_resident(flat, flat_id="00000000-0000-0000-0000-000000000000")

    response = await client.post(URL, json=payload, headers=auth_headers(admin))

    assert response.status_code == 404


async def primary_contact_ids(db: AsyncSession, flat_id: object) -> list[str]:
    rows = await db.scalars(
        select(Resident.id).where(Resident.flat_id == flat_id, Resident.is_primary_contact)
    )
    return [str(row) for row in rows]


async def test_only_one_primary_contact_per_flat(
    client: httpx2.AsyncClient, admin: User, flat: Flat, db: AsyncSession
) -> None:
    headers = auth_headers(admin)
    first = await client.post(
        URL, json=new_resident(flat, is_primary_contact=True), headers=headers
    )
    second = await client.post(
        URL,
        json=new_resident(flat, email="meera@example.com", is_primary_contact=True),
        headers=headers,
    )

    assert first.status_code == second.status_code == 201
    assert await primary_contact_ids(db, flat.id) == [second.json()["id"]]

    # Making the first one primary again moves the flag back.
    await client.patch(
        f"{URL}/{first.json()['id']}", json={"is_primary_contact": True}, headers=headers
    )
    assert await primary_contact_ids(db, flat.id) == [first.json()["id"]]


async def test_list_filters(
    client: httpx2.AsyncClient, admin: User, db: AsyncSession, society: Society, flat: Flat
) -> None:
    other_flat = await make_flat(db, society, "A", "101")
    await make_resident(db, society, flat, email="priya@test.in", full_name="Priya Sharma")
    await make_resident(db, society, other_flat, email="karan@test.in", full_name="Karan Mehta")
    headers = auth_headers(admin)

    by_block = (await client.get(URL, params={"block": "A"}, headers=headers)).json()
    by_flat = (await client.get(URL, params={"flat_id": str(flat.id)}, headers=headers)).json()
    by_name = (await client.get(URL, params={"q": "karan"}, headers=headers)).json()
    by_type = (await client.get(URL, params={"resident_type": "tenant"}, headers=headers)).json()
    active = (await client.get(URL, params={"is_active": True}, headers=headers)).json()

    assert [r["user"]["full_name"] for r in by_block["items"]] == ["Karan Mehta"]
    assert [r["user"]["email"] for r in by_flat["items"]] == ["priya@test.in"]
    assert by_name["total"] == 1
    assert by_type["total"] == 0
    assert active["total"] == 2


async def test_update_resident_fields_on_user_and_link(
    client: httpx2.AsyncClient, admin: User, resident: User, db: AsyncSession
) -> None:
    link = await db.scalar(select(Resident).where(Resident.user_id == resident.id))
    assert link is not None

    response = await client.patch(
        f"{URL}/{link.id}",
        json={"full_name": "Priya S. Sharma", "phone": None, "resident_type": "tenant"},
        headers=auth_headers(admin),
    )

    assert response.status_code == 200
    assert response.json()["user"]["full_name"] == "Priya S. Sharma"
    assert response.json()["user"]["phone"] is None
    assert response.json()["resident_type"] == "tenant"


async def test_deactivating_a_resident_revokes_sessions(
    client: httpx2.AsyncClient, admin: User, resident: User, db: AsyncSession
) -> None:
    await client.post(
        "/api/v1/auth/login", data={"username": "resident@test.in", "password": TEST_PASSWORD}
    )
    link = await db.scalar(select(Resident).where(Resident.user_id == resident.id))
    assert link is not None

    response = await client.patch(
        f"{URL}/{link.id}", json={"is_active": False}, headers=auth_headers(admin)
    )

    assert response.json()["user"]["is_active"] is False
    tokens = (
        await db.scalars(select(RefreshToken).where(RefreshToken.user_id == resident.id))
    ).all()
    assert tokens and all(t.revoked_at is not None for t in tokens)


async def test_removing_the_last_flat_deactivates_the_login(
    client: httpx2.AsyncClient, admin: User, resident: User, db: AsyncSession
) -> None:
    link = await db.scalar(select(Resident).where(Resident.user_id == resident.id))
    assert link is not None

    response = await client.delete(f"{URL}/{link.id}", headers=auth_headers(admin))

    assert response.status_code == 204
    await db.refresh(resident)
    assert resident.is_active is False
    assert (await client.get(f"{URL}/{link.id}", headers=auth_headers(admin))).status_code == 404


async def test_removing_one_of_two_flats_keeps_the_login(
    client: httpx2.AsyncClient, admin: User, resident: User, db: AsyncSession, society: Society
) -> None:
    second_flat = await make_flat(db, society, "C", "201")
    db.add(Resident(user_id=resident.id, flat_id=second_flat.id))
    await db.commit()
    link = await db.scalar(
        select(Resident).where(Resident.user_id == resident.id, Resident.flat_id == second_flat.id)
    )
    assert link is not None

    await client.delete(f"{URL}/{link.id}", headers=auth_headers(admin))

    await db.refresh(resident)
    assert resident.is_active is True
