"""Admin insights: analytics for the dashboard and the read-only audit log."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AdminUser, AppSettings, DbSession, Pagination, StaffUser
from app.schemas.analytics import AnalyticsOverview, AuditLogRead, InsideNowRead
from app.schemas.common import Page
from app.services import analytics, audit
from app.services.visitors import utcnow

router = APIRouter(tags=["insights"])


@router.get("/analytics/overview", response_model=AnalyticsOverview)
async def analytics_overview(
    admin: AdminUser,
    db: DbSession,
    settings: AppSettings,
    days: Annotated[int, Query(ge=1, le=90, description="Look back this many days")] = 14,
) -> AnalyticsOverview:
    """Busiest hours, visit durations, overstay rate, frequent visitors and what's inside
    right now. Hours and days are in IST."""
    result = await analytics.overview(db, settings, admin.society_id, now=utcnow(), days=days)
    return AnalyticsOverview.model_validate(result, from_attributes=True)


@router.get("/analytics/inside", response_model=InsideNowRead)
async def inside_now(staff: StaffUser, db: DbSession, settings: AppSettings) -> InsideNowRead:
    """Vehicles on the premises right now: the guard console's counter (staff)."""
    result = await analytics.inside_now(db, settings, staff.society_id, now=utcnow())
    return InsideNowRead.model_validate(result, from_attributes=True)


@router.get("/audit-logs", response_model=Page[AuditLogRead])
async def list_audit_logs(
    admin: AdminUser,
    db: DbSession,
    page: Pagination,
    entity_type: Annotated[str | None, Query(description="e.g. vehicle, flat, settings")] = None,
    actor_id: uuid.UUID | None = None,
) -> Page[AuditLogRead]:
    """Every admin change, newest first. Read-only."""
    result = await audit.list_entries(db, admin, page, entity_type=entity_type, actor_id=actor_id)
    return Page[AuditLogRead].model_validate(result, from_attributes=True)
