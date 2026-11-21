"""Test fixtures: a real Postgres test database, rolled back after every test.

How isolation works:
1. Once per run, the test database is recreated and migrated with Alembic (so the tests
   also prove the migrations work).
2. Each test opens one connection and starts a transaction on it.
3. Every session in the test (the fixtures' and each API request's) is bound to that
   connection in "savepoint" mode: their `commit()` only releases a savepoint.
4. When the test ends, the outer transaction is rolled back, so nothing is left behind
   and tests can run in any order.

In a test, re-read data with `db.refresh(obj)` or `db.expire_all()`. Don't call
`db.rollback()` / `db.reset()` mid-test: that rolls back the test session's savepoint,
which can also undo changes an API request made after it.

Set TEST_DATABASE_URL to use another server; by default it's DATABASE_URL + "_test".
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx2
import pytest
from alembic.config import Config
from redis.asyncio import Redis
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.api.deps import get_redis, get_snapshot_storage
from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models import Flat, Society, User
from app.models.enums import UserRole
from app.services.storage import LocalSnapshotStorage
from tests import factories

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _test_database_url() -> str:
    if explicit := os.environ.get("TEST_DATABASE_URL"):
        return explicit
    url = make_url(get_settings().database_url)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


def recreate_database(url: str) -> None:
    target = make_url(url)
    admin_engine = create_engine(
        target.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    with admin_engine.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{target.database}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{target.database}"'))
    admin_engine.dispose()


def alembic_config(url: str) -> Config:
    config = Config(BACKEND_DIR / "alembic.ini")
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    # "%" must be doubled: alembic.ini values go through configparser interpolation.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _test_database_url()
    recreate_database(url)
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="session")
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    test_engine = create_async_engine(database_url, poolclass=NullPool)
    yield test_engine
    await test_engine.dispose()


@pytest.fixture
async def connection(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    async with engine.connect() as conn:
        transaction = await conn.begin()
        yield conn
        await transaction.rollback()


def _session(connection: AsyncConnection) -> AsyncSession:
    return AsyncSession(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )


@pytest.fixture
async def db(connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    session = _session(connection)
    yield session
    await session.close()


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
    client = Redis.from_url(get_settings().redis_url, socket_connect_timeout=2)
    yield client
    await client.aclose()


@pytest.fixture
def snapshot_storage(tmp_path: Path) -> LocalSnapshotStorage:
    """Snapshots go to a temporary folder that pytest deletes afterwards."""
    return LocalSnapshotStorage(tmp_path / "snapshots")


@pytest.fixture
async def client(
    connection: AsyncConnection, redis_client: Redis, snapshot_storage: LocalSnapshotStorage
) -> AsyncIterator[httpx2.AsyncClient]:
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        session = _session(connection)
        try:
            yield session
        finally:
            await session.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis] = lambda: redis_client
    app.dependency_overrides[get_snapshot_storage] = lambda: snapshot_storage
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


# --- Ready-made people --------------------------------------------------------


@pytest.fixture
async def society(db: AsyncSession) -> Society:
    return await factories.make_society(db)


@pytest.fixture
async def admin(db: AsyncSession, society: Society) -> User:
    return await factories.make_user(db, society, UserRole.ADMIN, email="admin@test.in")


@pytest.fixture
async def guard(db: AsyncSession, society: Society) -> User:
    return await factories.make_user(db, society, UserRole.GUARD, email="guard@test.in")


@pytest.fixture
async def flat(db: AsyncSession, society: Society) -> Flat:
    return await factories.make_flat(db, society, "B", "402")


@pytest.fixture
async def resident(db: AsyncSession, society: Society, flat: Flat) -> User:
    return await factories.make_resident(db, society, flat, email="resident@test.in")
