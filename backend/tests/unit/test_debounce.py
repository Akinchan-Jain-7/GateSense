"""Debounce against a real Redis (the CI job and the dev stack both have one)."""

import uuid
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis

from app.services.debounce import check_and_mark

T0 = datetime(2026, 11, 21, 9, 0, tzinfo=UTC)
COOLDOWN = 30


async def _read(redis: Redis, device: uuid.UUID, plate: str, at: datetime) -> uuid.UUID | None:
    return await check_and_mark(
        redis,
        device_id=device,
        plate=plate,
        captured_at=at,
        new_event_id=uuid.uuid4(),
        cooldown_seconds=COOLDOWN,
    )


async def test_first_read_starts_a_new_event(redis_client: Redis) -> None:
    assert await _read(redis_client, uuid.uuid4(), "DL01AB1234", T0) is None


async def test_repeat_read_within_cooldown_joins_the_first_event(redis_client: Redis) -> None:
    device, first_id = uuid.uuid4(), uuid.uuid4()
    started = await check_and_mark(
        redis_client,
        device_id=device,
        plate="DL01AB1234",
        captured_at=T0,
        new_event_id=first_id,
        cooldown_seconds=COOLDOWN,
    )
    assert started is None
    assert await _read(redis_client, device, "DL01AB1234", T0 + timedelta(seconds=5)) == first_id


async def test_window_slides_while_the_car_waits(redis_client: Redis) -> None:
    device = uuid.uuid4()
    assert await _read(redis_client, device, "UP16Z5678", T0) is None
    # Seen every 20 s for a minute: each read is within 30 s of the previous one.
    for seconds in (20, 40, 60):
        assert await _read(redis_client, device, "UP16Z5678", T0 + timedelta(seconds=seconds))
    # Gone for 30 s or more: a new event.
    assert await _read(redis_client, device, "UP16Z5678", T0 + timedelta(seconds=95)) is None


async def test_reads_after_the_cooldown_are_new_events(redis_client: Redis) -> None:
    device = uuid.uuid4()
    assert await _read(redis_client, device, "HR26DK8337", T0) is None
    assert await _read(redis_client, device, "HR26DK8337", T0 + timedelta(seconds=30)) is None


async def test_capture_time_decides_not_arrival_time(redis_client: Redis) -> None:
    # Buffered reads replayed in a burst: an hour apart on the camera's clock.
    device = uuid.uuid4()
    assert await _read(redis_client, device, "KA05MN0042", T0) is None
    assert await _read(redis_client, device, "KA05MN0042", T0 + timedelta(hours=1)) is None


async def test_other_plates_and_other_lanes_are_independent(redis_client: Redis) -> None:
    entry, exit_lane = uuid.uuid4(), uuid.uuid4()
    assert await _read(redis_client, entry, "DL01AB1234", T0) is None
    assert await _read(redis_client, entry, "DL01AB1235", T0) is None  # another plate
    assert await _read(redis_client, exit_lane, "DL01AB1234", T0) is None  # another lane


async def test_redis_down_fails_open() -> None:
    dead = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)
    try:
        assert await _read(dead, uuid.uuid4(), "DL01AB1234", T0) is None
    finally:
        await dead.aclose()
