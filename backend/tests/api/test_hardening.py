"""Phase 7 hardening: request ids, security headers, CORS, body size limits, rate limits
and Prometheus metrics."""

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.middleware import SecurityHeadersMiddleware
from app.main import app
from app.models import Society, User
from app.models.enums import LaneDirection
from app.services import rate_limit
from app.services.errors import RateLimitedError
from tests import factories
from tests.api.test_gate_events import post_read
from tests.factories import auth_headers


def override(**changes: object) -> None:
    settings = get_settings().model_copy(update=changes)
    app.dependency_overrides[get_settings] = lambda: settings


# --- Request ids --------------------------------------------------------------------


async def test_every_response_has_a_request_id(client: httpx2.AsyncClient) -> None:
    response = await client.get("/health")
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])


async def test_a_sane_incoming_request_id_is_kept(client: httpx2.AsyncClient) -> None:
    kept = await client.get("/health", headers={"X-Request-ID": "lb-7f3a.42"})
    assert kept.headers["x-request-id"] == "lb-7f3a.42"
    replaced = await client.get("/health", headers={"X-Request-ID": "bad id\\nwith junk"})
    assert replaced.headers["x-request-id"] != "bad id\\nwith junk"


async def test_log_lines_carry_the_request_id(
    client: httpx2.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    from app.core.request_context import RequestIdFilter

    caplog.handler.addFilter(RequestIdFilter())
    with caplog.at_level("INFO", logger="gatesense.api"):
        response = await client.get("/health", headers={"X-Request-ID": "trace-me"})
    lines = [r for r in caplog.records if r.getMessage() == "request"]
    assert response.status_code == 200
    assert lines and getattr(lines[-1], "request_id", None) == "trace-me"
    assert getattr(lines[-1], "route", None) == "/health"


# --- Security headers and CORS ------------------------------------------------------


async def test_api_responses_carry_strict_security_headers(client: httpx2.AsyncClient) -> None:
    headers = (await client.get("/health")).headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["content-security-policy"].startswith("default-src 'none'")
    assert "strict-transport-security" not in headers  # only in production (HTTPS)


async def test_api_docs_keep_working_without_the_strict_csp(client: httpx2.AsyncClient) -> None:
    headers = (await client.get("/docs")).headers
    assert "content-security-policy" not in headers
    assert headers["x-content-type-options"] == "nosniff"


async def test_hsts_is_sent_in_production() -> None:
    sent: list[dict[str, object]] = []

    async def plain_app(scope: object, receive: object, send: Any) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})

    async def capture(message: dict[str, object]) -> None:
        sent.append(message)

    middleware = SecurityHeadersMiddleware(plain_app, hsts=True)
    await middleware({"type": "http", "path": "/health"}, None, capture)  # type: ignore[arg-type]
    headers = dict(sent[0]["headers"])  # type: ignore[call-overload]
    assert headers[b"strict-transport-security"].startswith(b"max-age=31536000")


async def test_the_visitor_page_allows_only_its_own_inline_code(
    client: httpx2.AsyncClient,
) -> None:
    response = await client.get("/visit/not-a-real-token")
    csp = response.headers["content-security-policy"]
    assert response.status_code == 404
    assert csp.startswith("default-src 'none'; style-src 'sha256-")
    assert "unsafe-inline" not in csp


async def test_cors_allows_only_the_configured_web_origin(client: httpx2.AsyncClient) -> None:
    preflight = {"Access-Control-Request-Method": "POST"}
    allowed = await client.options(
        "/api/v1/auth/login", headers={"Origin": "http://localhost:5173", **preflight}
    )
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    other = await client.options(
        "/api/v1/auth/login", headers={"Origin": "https://evil.example", **preflight}
    )
    assert "access-control-allow-origin" not in other.headers


# --- Body size limits ---------------------------------------------------------------


async def test_oversized_json_is_refused_before_it_is_read(
    client: httpx2.AsyncClient, admin: User
) -> None:
    huge = "x" * (get_settings().max_request_bytes + 10)
    response = await client.post(
        "/api/v1/flats",
        content=f'{{"block": "{huge}"}}',
        headers={**auth_headers(admin), "Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert "too large" in response.json()["detail"]


async def test_a_body_without_content_length_is_counted_as_it_streams(
    client: httpx2.AsyncClient,
) -> None:
    limit = get_settings().max_request_bytes

    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(limit // 65_536 + 2):
            yield b"a" * 65_536

    response = await client.post(
        "/api/v1/auth/refresh", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


async def test_camera_uploads_get_room_for_a_snapshot(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society
) -> None:
    gate = await factories.make_gate(db, society)
    _, key = await factories.make_device(db, gate, LaneDirection.ENTRY)
    snapshot = b"\xff\xd8\xff" + b"0" * 1_500_000  # bigger than the 1 MiB JSON limit
    response = await post_read(client, key, "DL01AB1234", snapshot=snapshot)
    assert response.status_code == 201


# --- Rate limits --------------------------------------------------------------------


async def test_login_is_limited_per_account(client: httpx2.AsyncClient, admin: User) -> None:
    override(login_rate_limit_per_account=3)
    form = {"username": admin.email, "password": "wrong-password"}
    for _ in range(3):
        assert (await client.post("/api/v1/auth/login", data=form)).status_code == 401
    blocked = await client.post("/api/v1/auth/login", data=form)
    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers["retry-after"]) <= 60
    # Even the right password waits until the minute is over.
    right = {"username": admin.email, "password": factories.TEST_PASSWORD}
    assert (await client.post("/api/v1/auth/login", data=right)).status_code == 429


async def test_login_is_limited_per_ip(client: httpx2.AsyncClient) -> None:
    override(login_rate_limit_per_ip=2)
    for i in range(2):
        form = {"username": f"someone{i}@example.com", "password": "x"}
        assert (await client.post("/api/v1/auth/login", data=form)).status_code == 401
    form = {"username": "someone-else@example.com", "password": "x"}
    assert (await client.post("/api/v1/auth/login", data=form)).status_code == 429


async def test_a_runaway_camera_is_slowed_down(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society
) -> None:
    override(device_rate_limit=2)
    gate = await factories.make_gate(db, society)
    _, key = await factories.make_device(db, gate, LaneDirection.ENTRY)
    now = datetime.now(UTC)
    for i in range(2):
        response = await post_read(client, key, f"DL01AB123{i}", at=now - timedelta(seconds=i))
        assert response.status_code == 201
    assert (await post_read(client, key, "DL01AB1239")).status_code == 429


async def test_the_limiter_lets_requests_through_when_redis_is_down() -> None:
    broken = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)
    await rate_limit.hit(broken, "login-ip", "203.0.113.7", limit=1)  # no exception
    await broken.aclose()


async def test_the_limiter_counts_per_window(redis_client: Redis) -> None:
    for _ in range(2):
        await rate_limit.hit(redis_client, "test", "who", limit=2)
    with pytest.raises(RateLimitedError):
        await rate_limit.hit(redis_client, "test", "who", limit=2)
    await rate_limit.hit(redis_client, "test", "someone-else", limit=2)  # separate counter


# --- Metrics ------------------------------------------------------------------------


async def test_metrics_are_served_in_prometheus_format(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society
) -> None:
    gate = await factories.make_gate(db, society)
    _, key = await factories.make_device(db, gate, LaneDirection.ENTRY)
    await post_read(client, key, "DL01AB1234")
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert 'http_requests_total{method="POST",route="/api/v1/gate-events",status="201"}' in body
    assert 'gate_events_total{match="unknown",status="created"}' in body
    assert "http_request_duration_seconds_bucket" in body
    assert "websocket_connections" in body


async def test_metrics_can_require_a_token(client: httpx2.AsyncClient) -> None:
    from pydantic import SecretStr

    override(metrics_token=SecretStr("scrape-me"))
    assert (await client.get("/metrics")).status_code == 401
    wrong = await client.get("/metrics", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401
    right = await client.get("/metrics", headers={"Authorization": "Bearer scrape-me"})
    assert right.status_code == 200


async def test_an_empty_metrics_token_means_open(client: httpx2.AsyncClient) -> None:
    from pydantic import SecretStr

    override(metrics_token=SecretStr(""))
    assert (await client.get("/metrics")).status_code == 200
