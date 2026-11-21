"""Database engine and session.

We use SQLAlchemy's async API with the psycopg 3 driver. psycopg 3 supports both sync and
async code, so the API (async) and, from Phase 5, Celery workers (sync) share one driver.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

CONNECT_TIMEOUT_SECONDS = 5


def create_engine(database_url: str) -> AsyncEngine:
    # pool_pre_ping: test a pooled connection before using it, so a restarted
    # Postgres doesn't cause "connection closed" errors on the first request.
    # connect_timeout: fail with a clear error instead of hanging if Postgres is unreachable.
    return create_async_engine(
        database_url, pool_pre_ping=True, connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS}
    )


engine = create_engine(get_settings().database_url)

# expire_on_commit=False: objects stay readable after commit (we often return them).
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, always closed afterwards.

    Services decide when to commit. If the request fails before a commit,
    closing the session rolls the transaction back.
    """
    async with SessionLocal() as session:
        yield session
