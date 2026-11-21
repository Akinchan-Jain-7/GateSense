"""Real-time events: publish to Redis channels, which WebSocket connections forward.

Why Redis pub/sub in between: the API may run as several processes (and Celery workers
publish too). A message published anywhere reaches every WebSocket connected to any
process, because each connection subscribes to Redis itself.

Channels:
- `console:<society>`: everything the guard console shows (arrivals, alerts, approvals).
- `user:<user>`: one person's events (a resident's approval requests and their visits).

Publishing never breaks the request that triggered it: if Redis is down, the change is
already committed, and clients catch up on their next reload. We log and move on.
"""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

PREFIX = "gatesense:rt"


def console_channel(society_id: uuid.UUID) -> str:
    return f"{PREFIX}:console:{society_id}"


def user_channel(user_id: uuid.UUID) -> str:
    return f"{PREFIX}:user:{user_id}"


def message(event_type: str, data: BaseModel | dict[str, Any]) -> str:
    payload = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
    return json.dumps(
        {"type": event_type, "at": datetime.now(UTC).isoformat(), "data": payload}, default=str
    )


async def publish(
    redis: Redis, channels: list[str], event_type: str, data: BaseModel | dict[str, Any]
) -> None:
    text = message(event_type, data)
    for channel in dict.fromkeys(channels):  # de-duplicate, keep order
        try:
            await redis.publish(channel, text)
        except RedisError:
            logger.warning("realtime publish failed", extra={"channel": channel}, exc_info=True)
