"""Per-society settings the admin can change: visit time limits, the approval timeout,
how long visitors' personal data is kept, the OCR confidence threshold and the number of
visitor parking spaces.

No row yet = the app defaults from config (so a fresh society works without setup).
The first save creates the row.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import SocietySettings, User
from app.models.enums import VisitCategory
from app.schemas.society_settings import VisitSettingsUpdate
from app.services import audit


@dataclass(frozen=True)
class VisitLimits:
    guest_minutes: int
    delivery_minutes: int
    cab_minutes: int
    service_minutes: int
    approval_timeout_seconds: int
    visitor_retention_days: int
    plate_confidence_threshold: float
    visitor_parking_slots: int

    def for_category(self, category: VisitCategory) -> timedelta:
        minutes = {
            VisitCategory.GUEST: self.guest_minutes,
            VisitCategory.DELIVERY: self.delivery_minutes,
            VisitCategory.CAB: self.cab_minutes,
            VisitCategory.SERVICE: self.service_minutes,
        }[category]
        return timedelta(minutes=minutes)

    @property
    def approval_timeout(self) -> timedelta:
        return timedelta(seconds=self.approval_timeout_seconds)


def defaults(settings: Settings) -> VisitLimits:
    return VisitLimits(
        guest_minutes=settings.visit_limit_guest_minutes,
        delivery_minutes=settings.visit_limit_delivery_minutes,
        cab_minutes=settings.visit_limit_cab_minutes,
        service_minutes=settings.visit_limit_service_minutes,
        approval_timeout_seconds=settings.approval_timeout_seconds,
        visitor_retention_days=settings.visitor_retention_days,
        plate_confidence_threshold=settings.plate_confidence_threshold,
        visitor_parking_slots=settings.visitor_parking_slots,
    )


async def visit_limits(db: AsyncSession, settings: Settings, society_id: uuid.UUID) -> VisitLimits:
    row = await db.get(SocietySettings, society_id)
    if row is None:
        return defaults(settings)
    return VisitLimits(
        guest_minutes=row.guest_minutes,
        delivery_minutes=row.delivery_minutes,
        cab_minutes=row.cab_minutes,
        service_minutes=row.service_minutes,
        approval_timeout_seconds=row.approval_timeout_seconds,
        visitor_retention_days=row.visitor_retention_days,
        plate_confidence_threshold=row.plate_confidence_threshold,
        visitor_parking_slots=row.visitor_parking_slots,
    )


async def update_visit_limits(
    db: AsyncSession, settings: Settings, admin: User, data: VisitSettingsUpdate
) -> VisitLimits:
    current = await visit_limits(db, settings, admin.society_id)
    changes = data.model_dump(exclude_unset=True)
    row = await db.get(SocietySettings, admin.society_id)
    if row is None:
        row = SocietySettings(society_id=admin.society_id, **current.__dict__)
        db.add(row)
    diff = {}
    for field, value in changes.items():
        old = getattr(row, field)
        if old != value:
            diff[field] = {"from": old, "to": value}
            setattr(row, field, value)
    if diff:
        audit.record(db, admin, "settings.update", None, diff)
    await db.commit()
    return await visit_limits(db, settings, admin.society_id)
