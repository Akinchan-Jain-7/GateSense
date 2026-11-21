"""Run async service code from a (synchronous) Celery task.

Each task gets a fresh event loop (`app.core.event_loop.run`), so it also needs its own
database engine and Redis client: pooled connections belong to the loop that created them.
NullPool = no pooling across tasks; one connection per task is plenty for these jobs.
"""

from collections.abc import Awaitable, Callable
from typing import TypeVar

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import event_loop
from app.core.config import Settings, get_settings
from app.db.session import CONNECT_TIMEOUT_SECONDS

T = TypeVar("T")

type Job[T] = Callable[[AsyncSession, Redis, Settings], Awaitable[T]]


async def _run[T](job: Job[T]) -> T:
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url,
        poolclass=NullPool,
        connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS},
    )
    redis = Redis.from_url(settings.redis_url, socket_connect_timeout=2)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            return await job(db, redis, settings)
    finally:
        await redis.aclose()
        await engine.dispose()


def run_job[T](job: Job[T]) -> T:
    return event_loop.run(_run(job))
