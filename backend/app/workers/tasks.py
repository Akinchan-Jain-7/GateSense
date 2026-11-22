"""Celery tasks. Each one is a thin wrapper: open a session, call a service, done.

Tasks are idempotent: running one twice (Celery retries, a worker crash after doing the
work but before acknowledging it) never repeats its effect.
"""

import logging
import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import Notification
from app.models.enums import ApprovalStatus, NotificationChannel, NotificationStatus
from app.services import telegram, visitors
from app.workers.celery_app import celery_app
from app.workers.runner import run_job

logger = logging.getLogger(__name__)


@celery_app.task(name="approvals.expire")  # type: ignore[untyped-decorator]
def expire_approval(approval_id: str) -> bool:
    async def job(db: AsyncSession, redis: Redis, settings: Settings) -> bool:
        return await visitors.expire_approval(db, redis, uuid.UUID(approval_id))

    return run_job(job)


async def send_approval(
    db: AsyncSession, settings: Settings, bot: telegram.TelegramBot, approval_id: uuid.UUID
) -> int:
    """Send an approval request to each linked resident once. Returns how many were sent."""
    approval = await visitors.load_approval(db, approval_id)
    if approval.status is not ApprovalStatus.PENDING:
        return 0
    sent = 0
    for user in await telegram.linked_residents(db, approval.visit.flat_id):
        key = f"approval:{approval.id}:telegram:{user.id}"
        note = await db.scalar(select(Notification).where(Notification.idempotency_key == key))
        if note is not None and note.status is NotificationStatus.SENT:
            continue
        if note is None:
            note = Notification(
                society_id=approval.visit.society_id,
                channel=NotificationChannel.TELEGRAM,
                kind="approval_request",
                recipient=str(user.telegram_chat_id),
                user_id=user.id,
                visit_id=approval.visit_id,
                idempotency_key=key,
                attempts=0,
            )
            db.add(note)
        note.attempts += 1
        try:
            assert user.telegram_chat_id is not None  # noqa: S101 - filtered by the query
            await bot.send_message(
                user.telegram_chat_id,
                telegram.approval_text(approval),
                telegram.approval_buttons(approval),
            )
        except Exception as exc:  # noqa: BLE001 - log any send failure on the notification
            note.status = NotificationStatus.FAILED
            note.last_error = str(exc)[:500]
            logger.warning("telegram send failed", extra={"approval_id": str(approval.id)})
        else:
            note.status = NotificationStatus.SENT
            note.sent_at = datetime.now(UTC)
            sent += 1
        await db.commit()
    return sent


@celery_app.task(name="approvals.telegram")  # type: ignore[untyped-decorator]
def send_approval_to_telegram(approval_id: str) -> int:
    async def job(db: AsyncSession, redis: Redis, settings: Settings) -> int:
        bot = telegram.build_bot(settings)
        if bot is None:
            return 0  # bot not configured: web approvals only
        try:
            return await send_approval(db, settings, bot, uuid.UUID(approval_id))
        finally:
            await bot.aclose()

    return run_job(job)


# --- Scheduled jobs (Celery Beat, see celery_app.beat_schedule) ----------------------------


@celery_app.task(name="escalation.tick")  # type: ignore[untyped-decorator]
def escalation_tick() -> dict[str, int]:
    from app.services import escalation

    async def job(db: AsyncSession, redis: Redis, settings: Settings) -> dict[str, int]:
        result = await escalation.run_ladder(db, redis, settings)
        swept = await escalation.sweep_approvals(db, redis)
        return {**result.__dict__, "approvals_timed_out": swept}

    return run_job(job)


@celery_app.task(name="notifications.dispatch")  # type: ignore[untyped-decorator]
def dispatch_notifications() -> dict[str, int]:
    from app.services import notifications

    async def job(db: AsyncSession, redis: Redis, settings: Settings) -> dict[str, int]:
        return await notifications.dispatch_due(db, notifications.SmtpMailer(settings), settings)

    return run_job(job)


@celery_app.task(name="reconciliation.nightly")  # type: ignore[untyped-decorator]
def nightly_reconciliation() -> dict[str, int]:
    from app.services import reconciliation

    async def job(db: AsyncSession, redis: Redis, settings: Settings) -> dict[str, int]:
        return await reconciliation.reconcile(db, settings)

    return run_job(job)


@celery_app.task(name="retention.daily")  # type: ignore[untyped-decorator]
def daily_retention() -> dict[str, int]:
    from app.services import retention
    from app.services.storage import build_snapshot_storage

    async def job(db: AsyncSession, redis: Redis, settings: Settings) -> dict[str, int]:
        return await retention.purge(db, build_snapshot_storage(settings), settings)

    return run_job(job)


@celery_app.task(name="demo.nightly_reset")  # type: ignore[untyped-decorator]
def nightly_demo_reset() -> dict[str, int]:
    from app.services import demo

    async def job(db: AsyncSession, redis: Redis, settings: Settings) -> dict[str, int]:
        summary = await demo.nightly_reset(db, settings, now=datetime.now(UTC))
        if summary is None:
            return {"reset": 0}
        return {"reset": 1, "history_visits": summary.history_visits}

    return run_job(job)
