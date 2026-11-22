"""Demo mode: one-click logins on the landing page and a "Reset demo" button for admins.

Both only work when DEMO_MODE=true. A real society's deployment leaves it off, so its
data can never be wiped from the UI and no login hints are published.
"""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app import seed
from app.core.config import Settings
from app.models import User
from app.services.errors import NotFoundError

ACCOUNTS = [
    ("guard", seed.DEMO_GUARD_EMAIL, "Ramesh Yadav"),
    ("resident", seed.DEMO_RESIDENT_EMAIL, "Priya Sharma"),
    ("admin", seed.DEMO_ADMIN_EMAIL, "Anil Mehta"),
]


def require_demo_mode(settings: Settings) -> None:
    if not settings.demo_mode:
        raise NotFoundError("Demo mode is off")


async def reset(
    db: AsyncSession, settings: Settings, admin: User, *, now: datetime
) -> seed.SeedSummary:
    """Wipe everything and seed again, with fresh history ending now and a few things
    happening at the gate right now. Every session ends:
    the users are recreated with new ids, so old tokens no longer match anyone."""
    require_demo_mode(settings)
    return await _reseed(db, settings, now=now)


async def nightly_reset(
    db: AsyncSession, settings: Settings, *, now: datetime
) -> seed.SeedSummary | None:
    """The scheduled reset of the public demo (Celery Beat, every night): visitors to the
    demo may have changed or deleted anything, so each day starts clean. Does nothing when
    demo mode is off, so this job can never wipe a real society's data."""
    if not settings.demo_mode:
        return None
    summary = await _reseed(db, settings, now=now)
    await db.commit()
    return summary


async def _reseed(db: AsyncSession, settings: Settings, *, now: datetime) -> seed.SeedSummary:
    await seed.reset_database(db)
    return await seed.seed(db, settings, history_days=seed.HISTORY_DAYS, now=now, live=True)
