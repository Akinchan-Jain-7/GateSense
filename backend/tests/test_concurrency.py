"""Races that only show up with real, separate database connections.

The usual `db` fixture shares one connection per test (rolled back afterwards), which
can't reproduce two requests waiting on each other's locks. These tests commit real rows
through independent sessions and delete them afterwards.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.config import get_settings
from app.models import Device, Flat, Gate, GateEvent, Society, Vehicle
from app.models.enums import LaneDirection
from app.services import gate_events, gates
from app.services.gate_events import PlateRead
from app.services.storage import LocalSnapshotStorage
from tests import factories


@pytest.fixture
async def committed(engine: AsyncEngine) -> AsyncIterator[dict[str, object]]:
    """A society with a resident car and two gates, really committed, cleaned up after."""
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        society = await factories.make_society(setup, f"Race {uuid.uuid4().hex[:6]}")
        flat = await factories.make_flat(setup, society, "R", "101")
        await factories.make_vehicle(setup, society, flat, "UP16RA4821")
        main = await factories.make_gate(setup, society, "Main Gate")
        service = await factories.make_gate(setup, society, "Service Gate")
        _, entry_key = await factories.make_device(setup, main, LaneDirection.ENTRY)
        _, exit_main = await factories.make_device(setup, main, LaneDirection.EXIT)
        _, exit_service = await factories.make_device(setup, service, LaneDirection.EXIT)
        await setup.commit()
    yield {"entry": entry_key, "exits": [exit_main, exit_service]}
    async with AsyncSession(engine) as cleanup:
        await cleanup.execute(delete(GateEvent).where(GateEvent.society_id == society.id))
        gate_ids = select(Gate.id).where(Gate.society_id == society.id)
        await cleanup.execute(delete(Device).where(Device.gate_id.in_(gate_ids)))
        await cleanup.execute(delete(Gate).where(Gate.society_id == society.id))
        await cleanup.execute(delete(Vehicle).where(Vehicle.society_id == society.id))
        await cleanup.execute(delete(Flat).where(Flat.society_id == society.id))
        await cleanup.execute(delete(Society).where(Society.id == society.id))
        await cleanup.commit()


async def read_at(
    engine: AsyncEngine, redis: Redis, storage: LocalSnapshotStorage, key: str, at: datetime
) -> gate_events.IngestResult:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        device = await gates.authenticate_device(session, key)
        read = PlateRead(plate_text="UP16RA4821", confidence=0.95, captured_at=at)
        return await gate_events.ingest_read(
            session, redis, storage, get_settings(), device, read, now=at
        )


async def test_two_simultaneous_exits_close_the_entry_once(
    engine: AsyncEngine,
    redis_client: Redis,
    snapshot_storage: LocalSnapshotStorage,
    committed: dict[str, object],
) -> None:
    """Found by the Phase 7 load test: two exit cameras read the same car at the same
    moment, both tried to pair with its open entry, and the loser got an HTTP 500."""
    keys = committed["exits"]
    assert isinstance(keys, list)
    start = datetime.now(UTC) - timedelta(hours=3)
    # Several rounds: a race doesn't lose every time, but it loses within a few tries.
    for round_ in range(6):
        entered = start + timedelta(minutes=20 * round_)
        left = entered + timedelta(minutes=10)
        entry = str(committed["entry"])
        await read_at(engine, redis_client, snapshot_storage, entry, entered)

        results = await asyncio.gather(
            *(read_at(engine, redis_client, snapshot_storage, key, left) for key in keys)
        )

        assert [r.status for r in results] == ["created", "created"]
        paired = [r.event.paired_event_id for r in results if r.event]
        assert sum(1 for p in paired if p is not None) == 1  # one closes it, one doesn't
