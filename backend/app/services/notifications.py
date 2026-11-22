"""Queueing and sending notifications (email and Telegram), with retries.

    queue_email(...)    -> a PENDING row with the rendered message; skipped if the same
    queue_telegram(...)    idempotency key was already queued (a job ran twice)
    dispatch_due(...)   -> the dispatcher job (every minute): sends due rows, marks SENT,
                           or schedules a retry with exponential backoff (1, 2, 4, 8 … min,
                           capped at 1 h); after `notification_max_attempts` it gives up
                           (FAILED) and the error stays on the row for the admin.

A Telegram approval request can't wait for the next minute (the resident has three), so
the approval job queues it and delivers it at once with `dispatch_due(only=...)`; only a
failed first try waits for the dispatcher. A retry for an approval that has been answered
in the meantime is CANCELLED instead of sent.

Rows are claimed with `FOR UPDATE SKIP LOCKED`, so two dispatchers running at once never
send the same row twice.
"""

import asyncio
import logging
import smtplib
import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any, Protocol

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import Approval, Notification
from app.models.enums import ApprovalStatus, NotificationChannel, NotificationStatus
from app.services.emails import Email

logger = logging.getLogger(__name__)

MAX_BACKOFF = timedelta(hours=1)


class Mailer(Protocol):
    async def send(self, to: str, email: Email) -> None: ...


class Messenger(Protocol):
    """What the dispatcher needs from the Telegram bot (app.services.telegram.TelegramBot)."""

    async def send_message(self, chat_id: int, text: str, buttons: Any = None) -> None: ...


class SmtpMailer:
    """Plain SMTP (Mailpit in development, any SMTP provider in production)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _send(self, to: str, email: Email) -> None:
        message = EmailMessage()
        message["From"] = self.settings.smtp_from
        message["To"] = to
        message["Subject"] = email.subject
        message.set_content(email.text)
        message.add_alternative(email.html, subtype="html")
        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=15) as smtp:
            if self.settings.smtp_starttls:
                smtp.starttls()
            if self.settings.smtp_username and self.settings.smtp_password:
                smtp.login(
                    self.settings.smtp_username, self.settings.smtp_password.get_secret_value()
                )
            smtp.send_message(message)

    async def send(self, to: str, email: Email) -> None:
        await asyncio.to_thread(self._send, to, email)  # smtplib blocks


async def queue_email(
    db: AsyncSession,
    *,
    society_id: uuid.UUID,
    kind: str,
    to: str,
    email: Email,
    key: str,
    user_id: uuid.UUID | None = None,
    visit_id: uuid.UUID | None = None,
) -> bool:
    """Queue an email unless `key` was queued before. Returns True if it was new."""
    inserted = await db.scalar(
        insert(Notification)
        .values(
            id=uuid.uuid4(),
            society_id=society_id,
            channel=NotificationChannel.EMAIL,
            kind=kind,
            recipient=to,
            user_id=user_id,
            visit_id=visit_id,
            status=NotificationStatus.PENDING,
            attempts=0,
            idempotency_key=key,
            subject=email.subject,
            body_text=email.text,
            body_html=email.html,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(Notification.id)
    )
    return inserted is not None


async def queue_telegram(
    db: AsyncSession,
    *,
    society_id: uuid.UUID,
    kind: str,
    chat_id: int,
    text: str,
    key: str,
    buttons: list[list[dict[str, str]]] | None = None,
    approval_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    visit_id: uuid.UUID | None = None,
) -> bool:
    """Queue a Telegram message unless `key` was queued before. Returns True if it was new."""
    inserted = await db.scalar(
        insert(Notification)
        .values(
            id=uuid.uuid4(),
            society_id=society_id,
            channel=NotificationChannel.TELEGRAM,
            kind=kind,
            recipient=str(chat_id),
            user_id=user_id,
            visit_id=visit_id,
            status=NotificationStatus.PENDING,
            attempts=0,
            idempotency_key=key,
            body_text=text,
            payload={
                "buttons": buttons,
                "approval_id": str(approval_id) if approval_id else None,
            },
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(Notification.id)
    )
    return inserted is not None


def backoff(attempts: int) -> timedelta:
    return min(MAX_BACKOFF, timedelta(minutes=2 ** max(0, attempts - 1)))


async def dispatch_due(
    db: AsyncSession,
    mailer: Mailer | None,
    settings: Settings,
    now: datetime | None = None,
    limit: int = 50,
    *,
    bot: Messenger | None = None,
    only: list[uuid.UUID] | None = None,
) -> dict[str, int]:
    """Send due notifications on the channels we can reach (email needs `mailer`, Telegram
    needs `bot`); `only` limits the run to those rows."""
    now = now or datetime.now(UTC)
    channels = [NotificationChannel.EMAIL] if mailer else []
    if bot:
        channels.append(NotificationChannel.TELEGRAM)
    counts = {"sent": 0, "retrying": 0, "failed": 0, "cancelled": 0}
    if not channels or only == []:
        return counts
    query = (
        select(Notification)
        .where(
            Notification.channel.in_(channels),
            Notification.status == NotificationStatus.PENDING,
            or_(Notification.next_attempt_at.is_(None), Notification.next_attempt_at <= now),
        )
        .order_by(Notification.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    if only is not None:
        query = query.where(Notification.id.in_(only))
    for note in (await db.scalars(query)).all():
        if await _no_longer_needed(db, note):
            note.status = NotificationStatus.CANCELLED
            counts["cancelled"] += 1
            continue
        note.attempts += 1
        try:
            await _deliver(note, mailer, bot)
        except Exception as exc:  # noqa: BLE001 - any send failure is recorded and retried
            note.last_error = f"{type(exc).__name__}: {exc}"[:500]
            if note.attempts >= settings.notification_max_attempts:
                note.status = NotificationStatus.FAILED
                counts["failed"] += 1
            else:
                note.next_attempt_at = now + backoff(note.attempts)
                counts["retrying"] += 1
            logger.warning("notification send failed", extra={"notification_id": str(note.id)})
        else:
            note.status = NotificationStatus.SENT
            note.sent_at = now
            note.last_error = None
            counts["sent"] += 1
    await db.commit()
    return counts


async def _deliver(note: Notification, mailer: Mailer | None, bot: Messenger | None) -> None:
    if note.channel is NotificationChannel.TELEGRAM:
        assert bot is not None  # noqa: S101 - only selected when a bot is configured
        buttons = (note.payload or {}).get("buttons")
        await bot.send_message(int(note.recipient), note.body_text or "", buttons)
        return
    assert mailer is not None  # noqa: S101 - only selected when a mailer is configured
    await mailer.send(
        note.recipient, Email(note.subject or "", note.body_text or "", note.body_html or "")
    )


async def _no_longer_needed(db: AsyncSession, note: Notification) -> bool:
    """An approval request whose approval was answered (or timed out) meanwhile."""
    approval_id = (note.payload or {}).get("approval_id")
    if not approval_id:
        return False
    approval = await db.get(Approval, uuid.UUID(approval_id))
    return approval is None or approval.status is not ApprovalStatus.PENDING
