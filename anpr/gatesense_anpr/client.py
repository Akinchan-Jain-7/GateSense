"""Sends plate reads to `POST /api/v1/gate-events`, retrying when the network or the
server has a problem.

- Network errors, timeouts, 429 and 5xx: retry with exponential backoff (0.5 s, 1 s, 2 s…).
  Retrying is safe because the server is idempotent: the same read (device, text,
  capture time) is stored once and returned with `status: duplicate` (ADR-0006).
- Other 4xx (bad key, invalid data): don't retry; raise `GateEventRejectedError`.
Buffering reads on disk while the server is down for longer is Phase 7 (offline mode).
"""

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

from gatesense_anpr.models import PlateRead

logger = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_BACKOFF_SECONDS = 8.0


class GateEventRejectedError(Exception):
    def __init__(self, status_code: int, detail: object) -> None:
        super().__init__(f"API rejected the read ({status_code}): {detail}")
        self.status_code = status_code
        self.detail = detail


class GateEventClient:
    def __init__(
        self,
        api_url: str,
        device_key: str,
        *,
        timeout: float = 10.0,
        max_retries: int = 4,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.http = httpx.Client(
            base_url=api_url.rstrip("/"),
            headers={"X-Device-Key": device_key},
            timeout=timeout,
            transport=transport,
        )
        self.max_retries = max_retries
        self.sleep = sleep

    def send(self, read: PlateRead) -> dict[str, Any]:
        data = {
            "plate_text": read.plate_text,
            "confidence": f"{read.confidence:.4f}",
            "captured_at": read.captured_at.isoformat(),
        }
        files = (
            {"snapshot": ("snapshot.jpg", read.snapshot_jpeg, "image/jpeg")}
            if read.snapshot_jpeg
            else None
        )
        for attempt in range(self.max_retries + 1):
            last_try = attempt == self.max_retries
            try:
                response = self.http.post("/api/v1/gate-events", data=data, files=files)
            except httpx.TransportError as exc:
                if last_try:
                    raise
                self._wait(attempt, f"network error: {exc}")
                continue
            if response.status_code in RETRY_STATUSES and not last_try:
                self._wait(attempt, f"HTTP {response.status_code}")
                continue
            if response.is_error:
                raise GateEventRejectedError(response.status_code, _detail(response))
            body: dict[str, Any] = response.json()
            return body
        raise AssertionError("unreachable")  # pragma: no cover

    def _wait(self, attempt: int, reason: str) -> None:
        delay = min(MAX_BACKOFF_SECONDS, 0.5 * 2**attempt)
        logger.warning("retrying gate event in %.1fs (%s)", delay, reason)
        self.sleep(delay)

    def close(self) -> None:
        self.http.close()


def _detail(response: httpx.Response) -> object:
    try:
        return response.json().get("detail", response.text)
    except ValueError:
        return response.text
