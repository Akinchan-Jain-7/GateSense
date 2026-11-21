import httpx2
from redis.asyncio import Redis

from app.api.system import get_redis
from app.main import app


async def test_health_returns_ok(client: httpx2.AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_openapi_docs_are_served(client: httpx2.AsyncClient) -> None:
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "GateSense API"


async def test_ready_when_database_and_redis_are_up(client: httpx2.AsyncClient) -> None:
    response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok", "redis": "ok"}}


async def test_not_ready_when_redis_is_down(client: httpx2.AsyncClient) -> None:
    # Port 1 has nothing listening, so the ping fails fast.
    unreachable = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.5)
    app.dependency_overrides[get_redis] = lambda: unreachable

    response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "ok", "redis": "error"}
    await unreachable.aclose()


async def test_lifespan_opens_and_closes_redis() -> None:
    async with app.router.lifespan_context(app):
        assert isinstance(app.state.redis, Redis)
