"""Alerts on the guard console (watchlist hits for now; more kinds arrive in later phases)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alert, User
from app.services.db_helpers import get_in_society
from app.services.pagination import PageRequest, PageResult, paginate


async def list_alerts(
    db: AsyncSession, actor: User, page: PageRequest, *, acknowledged: bool | None = None
) -> PageResult[Alert]:
    statement = (
        select(Alert).where(Alert.society_id == actor.society_id).order_by(Alert.created_at.desc())
    )
    if acknowledged is True:
        statement = statement.where(Alert.acknowledged_at.is_not(None))
    elif acknowledged is False:
        statement = statement.where(Alert.acknowledged_at.is_(None))
    return await paginate(db, statement, page)


async def acknowledge(db: AsyncSession, actor: User, alert_id: uuid.UUID) -> Alert:
    """Mark an alert as seen. Acknowledging twice keeps the first guard and time."""
    alert = await get_in_society(db, Alert, alert_id, actor.society_id)
    if alert.acknowledged_at is None:
        alert.acknowledged_at = datetime.now(UTC)
        alert.acknowledged_by_id = actor.id
        await db.commit()
    return alert
