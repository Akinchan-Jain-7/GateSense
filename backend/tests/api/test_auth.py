import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Flat, RefreshToken, Society, User
from app.models.enums import UserRole
from tests.factories import TEST_PASSWORD, auth_headers, make_user

LOGIN = "/api/v1/auth/login"


async def login(
    client: httpx2.AsyncClient, email: str, password: str = TEST_PASSWORD
) -> httpx2.Response:
    # OAuth2 password flow: a form with "username" (our email) and "password".
    return await client.post(LOGIN, data={"username": email, "password": password})


async def test_login_returns_a_token_pair(client: httpx2.AsyncClient, admin: User) -> None:
    response = await login(client, "admin@test.in")

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 15 * 60
    assert body["access_token"] and body["refresh_token"]


async def test_login_is_case_insensitive_and_records_last_login(
    client: httpx2.AsyncClient, admin: User, db: AsyncSession
) -> None:
    response = await login(client, "  ADMIN@Test.in ")

    assert response.status_code == 200
    await db.refresh(admin)
    assert admin.last_login_at is not None


async def test_wrong_password_and_unknown_email_get_the_same_error(
    client: httpx2.AsyncClient, admin: User
) -> None:
    wrong_password = await login(client, "admin@test.in", "not-the-password")
    unknown_email = await login(client, "nobody@test.in")

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert (
        wrong_password.json() == unknown_email.json() == {"detail": "Incorrect email or password"}
    )
    assert wrong_password.headers["WWW-Authenticate"] == "Bearer"


async def test_deactivated_user_cannot_log_in(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society
) -> None:
    await make_user(db, society, UserRole.GUARD, email="old.guard@test.in", is_active=False)

    response = await login(client, "old.guard@test.in")

    assert response.status_code == 401


async def test_me_returns_the_logged_in_user(client: httpx2.AsyncClient, guard: User) -> None:
    token = (await login(client, "guard@test.in")).json()["access_token"]

    response = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["email"] == "guard@test.in"
    assert response.json()["role"] == "guard"
    assert response.json()["flats"] == []


async def test_me_lists_a_residents_flats(
    client: httpx2.AsyncClient, resident: User, flat: Flat
) -> None:
    response = await client.get("/api/v1/me", headers=auth_headers(resident))

    assert response.json()["flats"] == [{"id": str(flat.id), "label": "B-402"}]


async def test_requests_without_or_with_bad_tokens_are_rejected(
    client: httpx2.AsyncClient,
) -> None:
    missing = await client.get("/api/v1/me")
    garbage = await client.get("/api/v1/me", headers={"Authorization": "Bearer not-a-jwt"})

    assert missing.status_code == garbage.status_code == 401


async def test_refresh_token_is_not_accepted_as_access_token(
    client: httpx2.AsyncClient, admin: User
) -> None:
    refresh_token = (await login(client, "admin@test.in")).json()["refresh_token"]

    response = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {refresh_token}"})

    assert response.status_code == 401


async def test_deactivating_a_user_locks_out_their_existing_access_token(
    client: httpx2.AsyncClient, db: AsyncSession, guard: User
) -> None:
    headers = auth_headers(guard)
    guard.is_active = False
    await db.commit()

    response = await client.get("/api/v1/me", headers=headers)

    assert response.status_code == 401


async def test_refresh_rotates_tokens(client: httpx2.AsyncClient, admin: User) -> None:
    first = (await login(client, "admin@test.in")).json()

    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )

    assert response.status_code == 200
    second = response.json()
    assert second["refresh_token"] != first["refresh_token"]
    me = await client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {second['access_token']}"}
    )
    assert me.status_code == 200


async def test_reusing_a_refresh_token_revokes_every_session(
    client: httpx2.AsyncClient, admin: User, db: AsyncSession
) -> None:
    stolen = await login(client, "admin@test.in")
    stolen_refresh = stolen.json()["refresh_token"]
    rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": stolen_refresh})
    new_refresh = rotated.json()["refresh_token"]

    replay = await client.post("/api/v1/auth/refresh", json={"refresh_token": stolen_refresh})

    assert replay.status_code == 401
    # The legitimate user's newer token was revoked too, as a precaution.
    after = await client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert after.status_code == 401
    tokens = (await db.scalars(select(RefreshToken).where(RefreshToken.user_id == admin.id))).all()
    assert all(token.revoked_at is not None for token in tokens)


async def test_logout_revokes_the_refresh_token(client: httpx2.AsyncClient, admin: User) -> None:
    refresh_token = (await login(client, "admin@test.in")).json()["refresh_token"]

    logout = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
    again = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
    refresh = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})

    assert logout.status_code == again.status_code == 204
    assert refresh.status_code == 401


async def test_refresh_with_an_access_token_or_garbage_fails(
    client: httpx2.AsyncClient, admin: User
) -> None:
    access_token = (await login(client, "admin@test.in")).json()["access_token"]

    with_access = await client.post("/api/v1/auth/refresh", json={"refresh_token": access_token})
    with_garbage = await client.post("/api/v1/auth/refresh", json={"refresh_token": "nope"})

    assert with_access.status_code == with_garbage.status_code == 401


async def test_refresh_fails_for_a_deactivated_user(
    client: httpx2.AsyncClient, admin: User, db: AsyncSession
) -> None:
    refresh_token = (await login(client, "admin@test.in")).json()["refresh_token"]
    admin.is_active = False
    await db.commit()

    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})

    assert response.status_code == 401
