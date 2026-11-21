"""Background jobs the API asks for, behind a small interface.

The API never imports Celery task objects directly: it asks a `JobQueue` (a FastAPI
dependency). In production that sends Celery tasks through Redis; tests swap in a
recorder, so they can check *what* was scheduled without running a worker.
"""

import logging
import uuid
from datetime import datetime
from typing import Protocol

logger = logging.getLogger(__name__)


class JobQueue(Protocol):
    def approval_timeout(self, approval_id: uuid.UUID, at: datetime) -> None: ...
    def notify_approval(self, approval_id: uuid.UUID) -> None: ...


class CeleryJobQueue:
    def approval_timeout(self, approval_id: uuid.UUID, at: datetime) -> None:
        from app.workers.tasks import expire_approval

        self._send(lambda: expire_approval.apply_async(args=[str(approval_id)], eta=at))

    def notify_approval(self, approval_id: uuid.UUID) -> None:
        from app.workers.tasks import send_approval_to_telegram

        self._send(lambda: send_approval_to_telegram.apply_async(args=[str(approval_id)]))

    @staticmethod
    def _send(send: object) -> None:
        # If the broker is down the request has already succeeded: the visit is saved and
        # the guard sees it. Log loudly; Phase 5's sweeper also expires overdue approvals.
        try:
            send()  # type: ignore[operator]
        except Exception:  # noqa: BLE001 - kombu raises many types; none may fail the request
            logger.exception("could not schedule background job")
