"""Role-based access control: every protected route, every role.

A forbidden role must get 403 *before* the route does anything, so a random id is
enough. An allowed role may get 200, 404 or 422 (we send no body), but never 401/403.
"""

import uuid

import httpx2
import pytest

from app.models import User
from tests.factories import auth_headers

ADMIN, GUARD, RESIDENT = "admin", "guard", "resident"
ANY_ID = uuid.uuid4()

# (method, path, roles allowed)
ROUTES = [
    ("GET", "/api/v1/me", {ADMIN, GUARD, RESIDENT}),
    ("GET", "/api/v1/flats", {ADMIN, GUARD}),
    ("GET", f"/api/v1/flats/{ANY_ID}", {ADMIN, GUARD}),
    ("POST", "/api/v1/flats", {ADMIN}),
    ("PATCH", f"/api/v1/flats/{ANY_ID}", {ADMIN}),
    ("DELETE", f"/api/v1/flats/{ANY_ID}", {ADMIN}),
    ("GET", "/api/v1/vehicles", {ADMIN, GUARD}),
    ("GET", f"/api/v1/vehicles/{ANY_ID}", {ADMIN, GUARD}),
    ("POST", "/api/v1/vehicles", {ADMIN}),
    ("PATCH", f"/api/v1/vehicles/{ANY_ID}", {ADMIN}),
    ("DELETE", f"/api/v1/vehicles/{ANY_ID}", {ADMIN}),
    ("GET", "/api/v1/residents", {ADMIN}),
    ("GET", f"/api/v1/residents/{ANY_ID}", {ADMIN}),
    ("POST", "/api/v1/residents", {ADMIN}),
    ("PATCH", f"/api/v1/residents/{ANY_ID}", {ADMIN}),
    ("DELETE", f"/api/v1/residents/{ANY_ID}", {ADMIN}),
    ("GET", "/api/v1/guards", {ADMIN}),
    ("GET", f"/api/v1/guards/{ANY_ID}", {ADMIN}),
    ("POST", "/api/v1/guards", {ADMIN}),
    ("PATCH", f"/api/v1/guards/{ANY_ID}", {ADMIN}),
    ("DELETE", f"/api/v1/guards/{ANY_ID}", {ADMIN}),
    ("GET", "/api/v1/gates", {ADMIN}),
    ("GET", f"/api/v1/gates/{ANY_ID}", {ADMIN}),
    ("POST", "/api/v1/gates", {ADMIN}),
    ("PATCH", f"/api/v1/gates/{ANY_ID}", {ADMIN}),
    ("DELETE", f"/api/v1/gates/{ANY_ID}", {ADMIN}),
    ("GET", "/api/v1/devices", {ADMIN}),
    ("GET", f"/api/v1/devices/{ANY_ID}", {ADMIN}),
    ("POST", "/api/v1/devices", {ADMIN}),
    ("POST", f"/api/v1/devices/{ANY_ID}/rotate-key", {ADMIN}),
    ("PATCH", f"/api/v1/devices/{ANY_ID}", {ADMIN}),
    ("DELETE", f"/api/v1/devices/{ANY_ID}", {ADMIN}),
    ("GET", "/api/v1/watchlist", {ADMIN}),
    ("GET", f"/api/v1/watchlist/{ANY_ID}", {ADMIN}),
    ("POST", "/api/v1/watchlist", {ADMIN}),
    ("PATCH", f"/api/v1/watchlist/{ANY_ID}", {ADMIN}),
    ("DELETE", f"/api/v1/watchlist/{ANY_ID}", {ADMIN}),
    ("GET", "/api/v1/gate-events", {ADMIN, GUARD}),
    ("GET", "/api/v1/gate-events/review-queue", {ADMIN, GUARD}),
    ("GET", f"/api/v1/gate-events/{ANY_ID}", {ADMIN, GUARD}),
    ("GET", f"/api/v1/gate-events/{ANY_ID}/snapshot", {ADMIN, GUARD}),
    ("POST", f"/api/v1/gate-events/{ANY_ID}/review", {ADMIN, GUARD}),
    ("GET", "/api/v1/alerts", {ADMIN, GUARD}),
    ("POST", f"/api/v1/alerts/{ANY_ID}/acknowledge", {ADMIN, GUARD}),
    ("POST", "/api/v1/visits", {ADMIN, GUARD}),
    ("GET", "/api/v1/visits", {ADMIN, GUARD, RESIDENT}),
    ("GET", f"/api/v1/visits/{ANY_ID}", {ADMIN, GUARD, RESIDENT}),
    ("POST", f"/api/v1/visits/{ANY_ID}/decision", {ADMIN, GUARD}),
    ("POST", f"/api/v1/visits/{ANY_ID}/enter", {ADMIN, GUARD}),
    ("POST", f"/api/v1/visits/{ANY_ID}/exit", {ADMIN, GUARD}),
    ("GET", "/api/v1/approvals", {ADMIN, GUARD, RESIDENT}),
    ("POST", f"/api/v1/approvals/{ANY_ID}/decision", {RESIDENT}),
    ("POST", "/api/v1/guest-passes", {RESIDENT}),
    ("GET", "/api/v1/guest-passes", {ADMIN, GUARD, RESIDENT}),
    ("POST", f"/api/v1/guest-passes/{ANY_ID}/revoke", {RESIDENT}),
    ("POST", "/api/v1/guest-passes/redeem", {ADMIN, GUARD}),
    ("GET", "/api/v1/settings/visits", {ADMIN, GUARD}),
    ("PATCH", "/api/v1/settings/visits", {ADMIN}),
    ("POST", "/api/v1/telegram/link-code", {RESIDENT}),
    ("DELETE", "/api/v1/telegram/link", {RESIDENT}),
    ("GET", "/api/v1/escalations", {ADMIN, GUARD}),
    ("POST", f"/api/v1/escalations/{ANY_ID}/resolve", {ADMIN, GUARD}),
    ("GET", "/api/v1/reconciliation", {ADMIN}),
    ("POST", f"/api/v1/reconciliation/{ANY_ID}/resolve", {ADMIN}),
    ("GET", "/api/v1/notifications", {ADMIN}),
    ("GET", "/api/v1/analytics/overview", {ADMIN}),
    ("GET", "/api/v1/analytics/inside", {ADMIN, GUARD}),
    ("GET", "/api/v1/audit-logs", {ADMIN}),
    ("POST", "/api/v1/demo/reset", {ADMIN}),
]


@pytest.fixture
def users(admin: User, guard: User, resident: User) -> dict[str, User]:
    return {ADMIN: admin, GUARD: guard, RESIDENT: resident}


@pytest.mark.parametrize(("method", "path", "allowed"), ROUTES)
async def test_role_access(
    client: httpx2.AsyncClient,
    users: dict[str, User],
    method: str,
    path: str,
    allowed: set[str],
) -> None:
    anonymous = await client.request(method, path)
    assert anonymous.status_code == 401

    for role, user in users.items():
        response = await client.request(method, path, headers=auth_headers(user))
        if role in allowed:
            assert response.status_code not in (401, 403), (role, response.text)
        else:
            assert response.status_code == 403, (role, response.text)
            detail = response.json()["detail"]
            assert all(name in detail for name in allowed), detail


def test_every_api_route_is_covered() -> None:
    """Adding a route without adding it to ROUTES should fail this test."""
    from app.main import app

    covered = {(m, p.replace(str(ANY_ID), "{id}")) for m, p, _ in ROUTES}
    schema_paths = app.openapi()["paths"]
    actual = set()
    for path, operations in schema_paths.items():
        if not path.startswith("/api/v1/") or path.startswith("/api/v1/auth/"):
            continue
        if path == "/api/v1/devices/me":  # device-key auth, tested separately
            continue
        if path.startswith("/api/v1/public/"):  # signed visitor links, no login by design
            continue
        if path == "/api/v1/demo":  # public on purpose: the landing page's demo logins
            continue
        if path == "/api/v1/gate-events":  # GET is staff; POST is device-key auth
            operations = {m: op for m, op in operations.items() if m != "post"}
        normalized = path
        for name in (
            "flat_id",
            "vehicle_id",
            "resident_id",
            "guard_id",
            "gate_id",
            "device_id",
            "entry_id",
            "event_id",
            "alert_id",
            "visit_id",
            "approval_id",
            "pass_id",
            "task_id",
            "flag_id",
        ):
            normalized = normalized.replace("{" + name + "}", "{id}")
        actual |= {(method.upper(), normalized) for method in operations}
    assert actual == covered
