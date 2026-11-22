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
from app.models.enums import ApprovalStatus, NotificationStatus
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
    """Queue the approval request for each linked resident (once each, however often the
    job runs) and deliver it straight away. Returns how many were sent now; a failed send
    stays queued and the dispatcher retries it with backoff."""
    from app.services import notifications

    approval = await visitors.load_approval(db, approval_id)
    if approval.status is not ApprovalStatus.PENDING:
        return 0
    prefix = f"approval:{approval.id}:telegram:"
    for user in await telegram.linked_residents(db, approval.visit.flat_id):
        assert user.telegram_chat_id is not None  # noqa: S101 - filtered by the query
        await notifications.queue_telegram(
            db,
            society_id=approval.visit.society_id,
            kind="approval_request",
            chat_id=user.telegram_chat_id,
            text=telegram.approval_text(approval),
            buttons=telegram.approval_buttons(approval),
            key=f"{prefix}{user.id}",
            approval_id=approval.id,
            user_id=user.id,
            visit_id=approval.visit_id,
        )
    await db.commit()
    queued = await db.scalars(
        select(Notification.id).where(
            Notification.idempotency_key.startswith(prefix),
            Notification.status == NotificationStatus.PENDING,
            Notification.next_attempt_at.is_(None),  # retries wait for the dispatcher
        )
    )
    counts = await notifications.dispatch_due(db, None, settings, bot=bot, only=list(queued))
    if counts["retrying"]:
        logger.warning("telegram send failed", extra={"approval_id": str(approval.id)})
    return counts["sent"]


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
        bot = telegram.build_bot(settings)  # None when Telegram isn't set up
        try:
            return await notifications.dispatch_due(
                db, notifications.SmtpMailer(settings), settings, bot=bot
            )
        finally:
            if bot is not None:
                await bot.aclose()

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
