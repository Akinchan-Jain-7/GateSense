"""Liveness and readiness probes, and Prometheus metrics.

- `/health` (liveness): "is the process alive?" Never touches other services, so a
  database outage doesn't make the platform restart a healthy API process.
- `/ready` (readiness): "can I serve traffic?" Checks Postgres and Redis; returns 503
  if either is down, so a load balancer stops sending requests here.
"""

import asyncio
import logging
import secrets
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel
from sqlalchemy import text

from app.api.deps import AppSettings, DbSession, RedisClient, get_redis
from app.core import metrics

__all__ = ["get_redis", "router"]  # get_redis is re-exported for tests

router = APIRouter(tags=["system"])
logger = logging.getLogger(__name__)

CHECK_TIMEOUT_SECONDS = 2.0


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, Literal["ok", "error"]]


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness check: answers as long as the process is running."""
    return {"status": "ok"}


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse, "description": "A dependency is down"}},
)
async def ready(response: Response, db: DbSession, redis: RedisClient) -> ReadinessResponse:
    checks: dict[str, Literal["ok", "error"]] = {}
    try:
        await asyncio.wait_for(db.execute(text("SELECT 1")), CHECK_TIMEOUT_SECONDS)
        checks["database"] = "ok"
    except Exception:  # any failure means "not ready"; the details go to the logs
        logger.warning("readiness check failed", extra={"check": "database"}, exc_info=True)
        checks["database"] = "error"
    try:
        await asyncio.wait_for(redis.ping(), CHECK_TIMEOUT_SECONDS)
        checks["redis"] = "ok"
    except Exception:
        logger.warning("readiness check failed", extra={"check": "redis"}, exc_info=True)
        checks["redis"] = "error"

    is_ready = all(result == "ok" for result in checks.values())
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ready" if is_ready else "not_ready", checks=checks)


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics(
    settings: AppSettings, authorization: str | None = Header(default=None)
) -> Response:
    """Prometheus scrape endpoint. Needs `Authorization: Bearer <METRICS_TOKEN>` when a
    token is configured (production); open otherwise (local development)."""
    token = settings.metrics_token.get_secret_value() if settings.metrics_token else ""
    if token:  # an empty METRICS_TOKEN= (copied from .env.example) means "not set"
        expected = f"Bearer {token}"
        if not secrets.compare_digest((authorization or "").encode(), expected.encode()):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Metrics token required")
    return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)
