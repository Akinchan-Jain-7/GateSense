"""The current request's id, available anywhere (logs, error reports) without passing it
around. A ContextVar is like a global, but each request (asyncio task) sees its own value.
"""

import logging
from contextvars import ContextVar

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIdFilter(logging.Filter):
    """Adds `request_id` to every log line written while a request is being handled."""

    def filter(self, record: logging.LogRecord) -> bool:
        current = request_id.get()
        if current is not None and not hasattr(record, "request_id"):
            record.request_id = current
        return True
