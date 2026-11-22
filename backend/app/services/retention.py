"""Daily privacy purge: personal data of visitors is kept only as long as needed.

After the society's `visitor_retention_days` (90 by default):
- **visitors** (name, phone, email) are deleted once none of their visits is recent or
  still open; their visits stay (for statistics) with `visitor_id` cleared;
- **notifications** keep their kind and status but lose the address and message text;
- **guest passes** that ended lose the guest's phone and name;
- **plate snapshots** (images of people and cars) are deleted from storage.
Gate events, visits and plate corrections stay: they hold plates, not names.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import GateEvent, GuestPass, Notification, Society, Visit, Visitor
from app.services.society_settings import visit_limits
from app.services.storage import SnapshotStorage
from app.services.visit_state import TERMINAL_STATUSES

REDACTED = "redacted"
SNAPSHOT_BATCH = 500


async def purge(
    db: AsyncSession, storage: SnapshotStorage, settings: Settings, now: datetime | None = None
) -> dict[str, int]:
    now = now or datetime.now(UTC)
    counts = {"visitors": 0, "notifications": 0, "guest_passes": 0, "snapshots": 0}
    for society_id in list(await db.scalars(select(Society.id))):
        limits = await visit_limits(db, settings, society_id)
        cutoff = now - timedelta(days=limits.visitor_retention_days)
        for key, value in (await _purge_society(db, storage, society_id, cutoff)).items():
            counts[key] += value
    return counts


async def _purge_society(
    db: AsyncSession, storage: SnapshotStorage, society_id: uuid.UUID, cutoff: datetime
) -> dict[str, int]:
    recent_or_open = exists().where(
        Visit.visitor_id == Visitor.id,
        or_(Visit.created_at >= cutoff, Visit.status.not_in(TERMINAL_STATUSES)),
    )
    visitors = await db.execute(
        delete(Visitor)
        .where(Visitor.society_id == society_id, Visitor.created_at < cutoff, ~recent_or_open)
        .returning(Visitor.id)
    )
    notes = await db.execute(
        update(Notification)
        .where(
            Notification.society_id == society_id,
            Notification.created_at < cutoff,
            Notification.recipient != REDACTED,
        )
        .values(recipient=REDACTED, subject=None, body_text=None, body_html=None, last_error=None)
        .returning(Notification.id)
    )
    passes = await db.execute(
        update(GuestPass)
        .where(
            GuestPass.society_id == society_id,
            GuestPass.valid_until < cutoff,
            or_(GuestPass.guest_phone.is_not(None), GuestPass.guest_name != "Guest"),
        )
        .values(guest_phone=None, guest_name="Guest")
        .returning(GuestPass.id)
    )
    counts = {
        "visitors": len(visitors.all()),
        "notifications": len(notes.all()),
        "guest_passes": len(passes.all()),
        "snapshots": 0,
    }
    await db.commit()

    while True:
        old = (
            await db.scalars(
                select(GateEvent)
                .where(
                    GateEvent.society_id == society_id,
                    GateEvent.captured_at < cutoff,
                    GateEvent.snapshot_path.is_not(None),
                )
                .limit(SNAPSHOT_BATCH)
            )
        ).all()
        if not old:
            break
        for event in old:
            assert event.snapshot_path is not None  # noqa: S101 - filtered above
            await storage.delete(event.snapshot_path)
            event.snapshot_path = None
        counts["snapshots"] += len(old)
        await db.commit()
    return counts
