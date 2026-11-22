"""Structured (JSON) logging with the standard library.

One JSON object per line is easy for humans to grep and for log tools (Loki, CloudWatch,
Render's log viewer) to parse. We use the stdlib `logging` module plus a small formatter
instead of adding a logging library.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.request_context import RequestIdFilter

# Attributes every LogRecord has; anything else was passed via `extra={...}`.
_STANDARD_ATTRS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Fields passed with `logger.info("...", extra={"user_id": ...})`.
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RequestIdFilter())  # every line logged during a request gets its id

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # Uvicorn's own loggers go through our JSON handler too. We log each request
    # ourselves (see the middleware in main.py), so uvicorn's access log is muted.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
