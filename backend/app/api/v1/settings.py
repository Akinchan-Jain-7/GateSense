from fastapi import APIRouter

from app.api.deps import AdminUser, AppSettings, DbSession, StaffUser
from app.schemas.society_settings import VisitSettingsRead, VisitSettingsUpdate
from app.services import society_settings as service

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/visits", response_model=VisitSettingsRead)
async def get_visit_settings(
    staff: StaffUser, db: DbSession, settings: AppSettings
) -> VisitSettingsRead:
    """Visit time limits per category and the approval timeout."""
    limits = await service.visit_limits(db, settings, staff.society_id)
    return VisitSettingsRead(**limits.__dict__)


@router.patch("/visits", response_model=VisitSettingsRead)
async def update_visit_settings(
    body: VisitSettingsUpdate, admin: AdminUser, db: DbSession, settings: AppSettings
) -> VisitSettingsRead:
    """Change limits (admin). Applies to visits that enter from now on. Audited."""
    limits = await service.update_visit_limits(db, settings, admin, body)
    return VisitSettingsRead(**limits.__dict__)
