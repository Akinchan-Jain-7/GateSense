"""Offline mode: keep plate reads on disk while the API can't be reached, then send them
in order when it's back.

Why this matters: a gate's internet link drops (power cuts, a router reboot, the ISP).
Cars keep coming. Without a buffer, every read during the outage is lost, and the visit
records stop making sense (an exit with no entry). With it:

1. A read that can't be delivered (network error, timeout, 429 or 5xx after the client's
   own retries) is written to a SQLite file. SQLite survives restarts and power cuts.
2. While anything is waiting, new reads queue *behind* it, so the server always receives
   reads in the order they happened. That keeps entry-before-exit pairing correct.
3. A flush sends the oldest reads first and stops at the first network failure, then
   waits (5 s, 10 s, 20 s ... up to 5 minutes) before trying again.
4. Replaying is safe: the server stores each read once, keyed by device + text + capture
   time (ADR-0006). A read that was delivered but whose reply got lost comes back as
   `status: duplicate`, not a second event.
5. A read the server rejects for good (4xx such as invalid data) moves to a `rejected`
   table for a human to look at, so one bad read can't block the queue forever.
"""

import json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import httpx

from gatesense_anpr.client import GateEventClient, GateEventRejectedError
from gatesense_anpr.models import PlateRead

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS pending (
    id INTEGER PRIMARY KEY AUTOINCREMENT,  -- insertion order = capture order
    plate_text TEXT NOT NULL,
    confidence REAL NOT NULL,
    captured_at TEXT NOT NULL,
    snapshot BLOB,
    votes INTEGER NOT NULL,
    raw_texts TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    queued_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS rejected (
    id INTEGER PRIMARY KEY,
    plate_text TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    detail TEXT NOT NULL,
    rejected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class OfflineBuffer:
    """A first-in, first-out queue of plate reads in a SQLite file."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # Autocommit: every push/remove is durable the moment it returns.
        # The live preview opens the buffer on one thread and sends from another, so the
        # connection may cross threads; the lock makes sure only one uses it at a time.
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(SCHEMA)

    def push(self, read: PlateRead) -> int:
        with self.lock:
            cursor = self.db.execute(
                "INSERT INTO pending"
                " (plate_text, confidence, captured_at, snapshot, votes, raw_texts)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    read.plate_text,
                    read.confidence,
                    read.captured_at.isoformat(),
                    read.snapshot_jpeg,
                    read.votes,
                    json.dumps(list(read.raw_texts)),
                ),
            )
            return int(cursor.lastrowid or 0)

    def oldest(self, limit: int = 50) -> list[tuple[int, PlateRead]]:
        with self.lock:
            rows = self.db.execute(
                "SELECT id, plate_text, confidence, captured_at, snapshot, votes, raw_texts"
                " FROM pending ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                (
                    row_id,
                    PlateRead(
                        plate_text=text,
                        confidence=confidence,
                        captured_at=datetime.fromisoformat(captured_at),
                        snapshot_jpeg=snapshot,
                        votes=votes,
                        raw_texts=tuple(json.loads(raw_texts)),
                    ),
                )
                for row_id, text, confidence, captured_at, snapshot, votes, raw_texts in rows
            ]

    def remove(self, row_id: int) -> None:
        with self.lock:
            self.db.execute("DELETE FROM pending WHERE id = ?", (row_id,))

    def record_failure(self, row_id: int, error: str) -> None:
        with self.lock:
            self.db.execute(
                "UPDATE pending SET attempts = attempts + 1, last_error = ? WHERE id = ?",
                (error[:500], row_id),
            )

    def reject(self, row_id: int, read: PlateRead, status_code: int, detail: object) -> None:
        with self.lock, self.db:  # both statements or neither
            self.db.execute("BEGIN")
            self.db.execute(
                "INSERT INTO rejected (id, plate_text, captured_at, status_code, detail)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    row_id,
                    read.plate_text,
                    read.captured_at.isoformat(),
                    status_code,
                    str(detail),
                ),
            )
            self.db.execute("DELETE FROM pending WHERE id = ?", (row_id,))

    def __len__(self) -> int:
        with self.lock:
            return int(self.db.execute("SELECT COUNT(*) FROM pending").fetchone()[0])

    def rejected_count(self) -> int:
        with self.lock:
            return int(self.db.execute("SELECT COUNT(*) FROM rejected").fetchone()[0])

    def close(self) -> None:
        with self.lock:
            self.db.close()


Outcome = Literal["sent", "buffered", "rejected"]


@dataclass
class FlushResult:
    sent: int = 0
    rejected: int = 0
    remaining: int = 0
    skipped: bool = False  # still waiting before the next attempt


def _is_offline(error: Exception) -> bool:
    """Network trouble or a server that's struggling: keep the read and try later."""
    if isinstance(error, httpx.TransportError):
        return True
    return isinstance(error, GateEventRejectedError) and error.retryable


class BufferedSender:
    """Sends reads through `client`, falling back to `buffer` while the API is away."""

    def __init__(
        self,
        client: GateEventClient,
        buffer: OfflineBuffer,
        *,
        on_sent: Callable[[PlateRead, dict[str, Any]], None] | None = None,
        on_rejected: Callable[[PlateRead, GateEventRejectedError], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        first_wait: float = 5.0,
        max_wait: float = 300.0,
    ) -> None:
        self.client = client
        self.buffer = buffer
        self.on_sent = on_sent
        self.on_rejected = on_rejected
        self.clock = clock
        self.first_wait = first_wait
        self.max_wait = max_wait
        self._failures = 0
        self._next_attempt = 0.0

    def send(self, read: PlateRead) -> Outcome:
        if len(self.buffer) > 0:
            # Something older is still waiting: queue behind it to keep the order.
            self.buffer.push(read)
            self.flush()
            return "buffered"
        try:
            result = self.client.send(read)
        except Exception as error:
            if _is_offline(error):
                self.buffer.push(read)
                self._schedule_retry(str(error))
                logger.warning("API unreachable, buffered %s (%s)", read.plate_text, error)
                return "buffered"
            if isinstance(error, GateEventRejectedError):
                logger.error("%s", error)
                if self.on_rejected:
                    self.on_rejected(read, error)
                return "rejected"
            raise
        self._failures = 0
        if self.on_sent:
            self.on_sent(read, result)
        return "sent"

    def flush(self, *, force: bool = False) -> FlushResult:
        """Send waiting reads, oldest first, until the queue is empty or the network fails."""
        result = FlushResult()
        if not force and self.clock() < self._next_attempt:
            result.skipped = True
            result.remaining = len(self.buffer)
            return result
        while batch := self.buffer.oldest():
            for row_id, read in batch:
                try:
                    reply = self.client.send(read)
                except Exception as error:
                    if _is_offline(error):
                        self.buffer.record_failure(row_id, str(error))
                        self._schedule_retry(str(error))
                        result.remaining = len(self.buffer)
                        return result
                    if isinstance(error, GateEventRejectedError):
                        logger.error("dropping buffered read %s: %s", read.plate_text, error)
                        self.buffer.reject(row_id, read, error.status_code, error.detail)
                        if self.on_rejected:
                            self.on_rejected(read, error)
                        result.rejected += 1
                        continue
                    raise
                self.buffer.remove(row_id)
                result.sent += 1
                if self.on_sent:
                    self.on_sent(read, reply)
        self._failures = 0
        self._next_attempt = 0.0
        if result.sent:
            logger.info("offline buffer drained: %d read(s) sent", result.sent)
        return result

    def _schedule_retry(self, reason: str) -> None:
        wait = min(self.max_wait, self.first_wait * 2**self._failures)
        self._failures += 1
        self._next_attempt = self.clock() + wait
        logger.info("next delivery attempt in %.0fs (%s)", wait, reason)
