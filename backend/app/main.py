"""GateSense API entry point: builds the FastAPI app and wires everything together."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.api import public, system
from app.api.errors import register_error_handlers
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.event_loop import check_running_loop
from app.core.logging import configure_logging
from app.core.middleware import (
    BodySizeLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.db.session import engine
from app.services.storage import build_snapshot_storage
from app.services.telegram import build_bot
from app.workers.jobs import CeleryJobQueue

logger = logging.getLogger("gatesense.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Runs once at start-up (before `yield`) and once at shutdown (after it)."""
    settings = get_settings()
    configure_logging(settings.log_level)
    check_running_loop()
    app.state.redis = Redis.from_url(settings.redis_url, socket_connect_timeout=2)
    app.state.snapshot_storage = build_snapshot_storage(settings)
    app.state.jobs = CeleryJobQueue()
    app.state.telegram_bot = build_bot(settings)
    logger.info("api started", extra={"env": settings.app_env})
    yield
    await app.state.redis.aclose()
    if app.state.telegram_bot is not None:
        await app.state.telegram_bot.aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="GateSense API",
        version="0.1.0",
        description="AI-powered society gate and visitor management.",
        lifespan=lifespan,
    )
    # Middleware runs outermost-last-added: request context wraps everything, so even a
    # 413 from the size limit gets a request id, a log line and a metric.
    app.add_middleware(
        BodySizeLimitMiddleware,
        default_limit=settings.max_request_bytes,
        upload_limit=settings.snapshot_max_bytes + 65_536,
    )
    # CORS: only the configured web origins, only the methods and headers the app uses.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,  # bearer tokens, no cookies
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.app_env == "production")
    app.add_middleware(RequestContextMiddleware)

    register_error_handlers(app)
    app.include_router(system.router)
    app.include_router(public.router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
