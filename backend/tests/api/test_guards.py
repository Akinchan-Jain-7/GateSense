import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Society, User
from app.models.enums import UserRole
from tests.factories import TEST_PASSWORD, auth_headers, make_user

URL = "/api/v1/guards"


async def test_create_and_log_in_as_a_new_guard(client: httpx2.AsyncClient, admin: User) -> None:
    response = await client.post(
        URL,
        json={
            "full_name": "Suresh Kumar",
            "email": "suresh@example.com",
            "phone": "+91 99887 76655",
            "password": "night-shift-2026",
        },
        headers=auth_headers(admin),
    )
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": "suresh@example.com", "password": "night-shift-2026"},
    )

    assert response.status_code == 201
    assert response.json()["phone"] == "+919988776655"
    assert login.status_code == 200


async def test_duplicate_email_is_a_conflict(
    client: httpx2.AsyncClient, admin: User, guard: User
) -> None:
    response = await client.post(
        URL,
        json={"full_name": "Copy", "email": "guard@test.in", "password": "whatever-123"},
        headers=auth_headers(admin),
    )

    assert response.status_code == 409


async def test_list_only_shows_guards(
    client: httpx2.AsyncClient, admin: User, guard: User, resident: User
) -> None:
    response = await client.get(URL, headers=auth_headers(admin))

    assert [g["email"] for g in response.json()["items"]] == ["guard@test.in"]


async def test_list_filters(
    client: httpx2.AsyncClient, admin: User, guard: User, db: AsyncSession, society: Society
) -> None:
    await make_user(
        db, society, UserRole.GUARD, email="mohan@test.in", full_name="Mohan Rawat", is_active=False
    )
    headers = auth_headers(admin)

    active = (await client.get(URL, params={"is_active": True}, headers=headers)).json()
    search = (await client.get(URL, params={"q": "mohan"}, headers=headers)).json()

    assert [g["email"] for g in active["items"]] == ["guard@test.in"]
    assert [g["email"] for g in search["items"]] == ["mohan@test.in"]


async def test_a_resident_id_is_not_a_guard(
    client: httpx2.AsyncClient, admin: User, resident: User
) -> None:
    response = await client.get(f"{URL}/{resident.id}", headers=auth_headers(admin))

    assert response.status_code == 404


async def test_update_and_deactivate_via_patch(
    client: httpx2.AsyncClient, admin: User, guard: User
) -> None:
    response = await client.patch(
        f"{URL}/{guard.id}",
        json={"full_name": "Ramesh Yadav", "is_active": False},
        headers=auth_headers(admin),
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    login = await client.post(
        "/api/v1/auth/login", data={"username": "guard@test.in", "password": TEST_PASSWORD}
    )
    assert login.status_code == 401


async def test_delete_deactivates_and_keeps_the_record(
    client: httpx2.AsyncClient, admin: User, guard: User
) -> None:
    headers = auth_headers(admin)

    first = await client.delete(f"{URL}/{guard.id}", headers=headers)
    second = await client.delete(f"{URL}/{guard.id}", headers=headers)  # idempotent
    record = await client.get(f"{URL}/{guard.id}", headers=headers)

    assert first.status_code == second.status_code == 204
    assert record.json()["is_active"] is False
