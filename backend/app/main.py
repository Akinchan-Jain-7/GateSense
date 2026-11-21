"""GateSense API entry point: builds the FastAPI app and wires everything together."""

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.api import system
from app.api.errors import register_error_handlers
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import engine

logger = logging.getLogger("gatesense.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Runs once at start-up (before `yield`) and once at shutdown (after it)."""
    settings = get_settings()
    configure_logging(settings.log_level)
    app.state.redis = Redis.from_url(settings.redis_url, socket_connect_timeout=2)
    logger.info("api started", extra={"env": settings.app_env})
    yield
    await app.state.redis.aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="GateSense API",
        version="0.1.0",
        description="AI-powered society gate and visitor management.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_requests(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return response

    register_error_handlers(app)
    app.include_router(system.router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
