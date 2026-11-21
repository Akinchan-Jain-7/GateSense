import httpx2

from app.models import User
from tests.factories import auth_headers

URL = "/api/v1/watchlist"


async def test_watchlist_crud(client: httpx2.AsyncClient, admin: User) -> None:
    headers = auth_headers(admin)

    created = await client.post(
        URL, json={"plate": "hr26 dk 8337", "reason": "Rash driving complaint"}, headers=headers
    )
    entry_id = created.json()["id"]
    duplicate = await client.post(
        URL, json={"plate": "HR26DK8337", "reason": "Again"}, headers=headers
    )
    updated = await client.patch(f"{URL}/{entry_id}", json={"is_active": False}, headers=headers)
    fetched = await client.get(f"{URL}/{entry_id}", headers=headers)
    search = await client.get(URL, params={"q": "dk83", "is_active": False}, headers=headers)
    deleted = await client.delete(f"{URL}/{entry_id}", headers=headers)
    gone = await client.get(f"{URL}/{entry_id}", headers=headers)

    assert created.status_code == 201
    assert created.json()["plate_normalized"] == "HR26DK8337"
    assert created.json()["added_by_id"] == str(admin.id)
    assert duplicate.status_code == 409
    assert updated.json()["is_active"] is False
    assert fetched.status_code == 200
    assert search.json()["total"] == 1
    assert deleted.status_code == 204
    assert gone.status_code == 404


async def test_invalid_watchlist_plate(client: httpx2.AsyncClient, admin: User) -> None:
    response = await client.post(
        URL, json={"plate": "NOTAPLATE", "reason": "test"}, headers=auth_headers(admin)
    )

    assert response.status_code == 422
