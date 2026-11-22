"""Rate limiting with a fixed one-minute window in Redis.

Each (scope, who) pair gets a counter key per minute, e.g.
`ratelimit:login-ip:203.0.113.7:29483021`. INCR + EXPIRE run in one round trip; once the
count passes the limit, requests get 429 with a Retry-After until the minute ends.

Fixed windows are the simplest scheme that works: at worst a client gets 2x the limit
across a minute boundary, which is fine for slowing down password guessing and stopping
a runaway camera. (A sliding window or token bucket is smoother, and more code.)

If Redis is down we let the request through, like the debounce step: refusing every
login because the limiter is broken would be worse than briefly not limiting.
"""

import logging
import time

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core import metrics
from app.services.errors import RateLimitedError

logger = logging.getLogger(__name__)


async def hit(redis: Redis, scope: str, who: str, *, limit: int, window_seconds: int = 60) -> None:
    """Count one request; raise RateLimitedError if `who` is over `limit` in this window."""
    now = time.time()
    window = int(now // window_seconds)
    key = f"ratelimit:{scope}:{who}:{window}"
    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_seconds + 5)
            count, _ = await pipe.execute()
    except RedisError:
        logger.warning("rate limiter unavailable, allowing request", extra={"scope": scope})
        return
    if int(count) > limit:
        metrics.rate_limited.labels(scope).inc()
        retry_after = max(1, int(window_seconds - now % window_seconds))
        raise RateLimitedError("Too many requests. Try again in a minute.", retry_after)
