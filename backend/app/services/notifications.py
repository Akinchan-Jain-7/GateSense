"""Queueing and sending notifications, with retries.

    queue_email(...)  -> a PENDING row with the rendered message; skipped if the same
                         idempotency key was already queued (a job ran twice)
    dispatch_due(...) -> the dispatcher job (every minute): sends due rows, marks SENT,
                         or schedules a retry with exponential backoff (1, 2, 4, 8 … min,
                         capped at 1 h); after `notification_max_attempts` it gives up
                         (FAILED) and the error stays on the row for the admin.

Rows are claimed with `FOR UPDATE SKIP LOCKED`, so two dispatchers running at once never
send the same row twice.
"""

import asyncio
import logging
import smtplib
import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import Notification
from app.models.enums import NotificationChannel, NotificationStatus
from app.services.emails import Email

logger = logging.getLogger(__name__)

MAX_BACKOFF = timedelta(hours=1)


class Mailer(Protocol):
    async def send(self, to: str, email: Email) -> None: ...


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


def backoff(attempts: int) -> timedelta:
    return min(MAX_BACKOFF, timedelta(minutes=2 ** max(0, attempts - 1)))


async def dispatch_due(
    db: AsyncSession,
    mailer: Mailer,
    settings: Settings,
    now: datetime | None = None,
    limit: int = 50,
) -> dict[str, int]:
    now = now or datetime.now(UTC)
    rows = (
        await db.scalars(
            select(Notification)
            .where(
                Notification.channel == NotificationChannel.EMAIL,
                Notification.status == NotificationStatus.PENDING,
                or_(Notification.next_attempt_at.is_(None), Notification.next_attempt_at <= now),
            )
            .order_by(Notification.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    counts = {"sent": 0, "retrying": 0, "failed": 0}
    for note in rows:
        note.attempts += 1
        try:
            await mailer.send(
                note.recipient,
                Email(note.subject or "", note.body_text or "", note.body_html or ""),
            )
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
