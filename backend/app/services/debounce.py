"""Debounce: one car in front of a camera is one gate event, not one per video frame.

A camera sees the same plate many times while a car waits at the barrier. We remember,
per lane (device) and plate, *when* it was last seen and which event it created. A new
read of the same plate on the same lane within the cooldown is folded into that event.

Two details matter:
- The window **slides**: every read pushes "last seen" forward, so a car parked at the
  gate for two minutes is still one event. A new event starts only after the plate has
  been out of view for a full cooldown.
- Times are **capture times** from the camera, not arrival times at the server. When an
  offline camera (Phase 7) uploads an hour of buffered reads in a few seconds, two visits
  an hour apart must stay two events.

The check-and-update runs as one Lua script inside Redis, so two requests arriving at the
same moment can't both decide they are first. If Redis is down we *fail open* (accept the
read): a duplicate event is better than a missed car, and exact retries are still caught
by the event hash in Postgres.
"""

import logging
import uuid
from datetime import datetime

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

KEY_PREFIX = "gatesense:debounce"

# KEYS[1] = debounce key; ARGV = capture time (ms), new event id, window (ms), TTL (s).
# Stored value: "<last seen ms>|<event id that started the window>".
_DEBOUNCE_SCRIPT = """
local now = tonumber(ARGV[1])
local current = redis.call('GET', KEYS[1])
if current then
  local sep = string.find(current, '|', 1, true)
  local last_seen = tonumber(string.sub(current, 1, sep - 1))
  local first_event = string.sub(current, sep + 1)
  if math.abs(now - last_seen) < tonumber(ARGV[3]) then
    local newest = string.format('%.0f', math.max(now, last_seen))
    redis.call('SET', KEYS[1], newest .. '|' .. first_event, 'EX', ARGV[4])
    return first_event
  end
end
redis.call('SET', KEYS[1], ARGV[1] .. '|' .. ARGV[2], 'EX', ARGV[4])
return false
"""


# Undo a mark whose event was never saved (storage or database failed after the check),
# so the camera's retry starts a new event instead of being folded into nothing. Only
# deletes the key if it still names that event: a newer window is left alone.
_RELEASE_SCRIPT = """
local current = redis.call('GET', KEYS[1])
if current then
  local sep = string.find(current, '|', 1, true)
  if string.sub(current, sep + 1) == ARGV[1] then
    redis.call('DEL', KEYS[1])
    return 1
  end
end
return 0
"""


def debounce_key(device_id: uuid.UUID, plate: str) -> str:
    return f"{KEY_PREFIX}:{device_id}:{plate}"


async def check_and_mark(
    redis: Redis,
    *,
    device_id: uuid.UUID,
    plate: str,
    captured_at: datetime,
    new_event_id: uuid.UUID,
    cooldown_seconds: int,
) -> uuid.UUID | None:
    """Returns the id of the event this read belongs to, or None if it starts a new one.

    When None is returned, `new_event_id` has been recorded as the start of a new window.
    """
    captured_ms = int(captured_at.timestamp() * 1000)
    try:
        result = await redis.eval(
            _DEBOUNCE_SCRIPT,
            1,
            debounce_key(device_id, plate),
            str(captured_ms),
            str(new_event_id),
            str(cooldown_seconds * 1000),
            str(cooldown_seconds),
        )
    except RedisError:
        logger.warning("debounce unavailable, accepting read", exc_info=True)
        return None
    if result is None:
        return None
    return uuid.UUID(result.decode() if isinstance(result, bytes) else str(result))


async def release(redis: Redis, *, device_id: uuid.UUID, plate: str, event_id: uuid.UUID) -> None:
    """Forget the window `event_id` started, if it is still the current one."""
    try:
        await redis.eval(_RELEASE_SCRIPT, 1, debounce_key(device_id, plate), str(event_id))
    except RedisError:
        logger.warning("could not release a debounce mark", exc_info=True)
