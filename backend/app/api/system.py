"""Liveness and readiness probes.

- `/health` (liveness): "is the process alive?" Never touches other services, so a
  database outage doesn't make the platform restart a healthy API process.
- `/ready` (readiness): "can I serve traffic?" Checks Postgres and Redis; returns 503
  if either is down, so a load balancer stops sending requests here.
"""

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from app.api.deps import DbSession, RedisClient, get_redis

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
