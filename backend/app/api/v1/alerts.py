import uuid

from fastapi import APIRouter

from app.api.deps import DbSession, Pagination, StaffUser
from app.schemas.common import Page
from app.schemas.gate_event import AlertRead
from app.services import alerts as service

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=Page[AlertRead])
async def list_alerts(
    staff: StaffUser, db: DbSession, page: Pagination, acknowledged: bool | None = None
) -> Page[AlertRead]:
    """Alerts for the guard console, newest first. `acknowledged=false` = still open."""
    result = await service.list_alerts(db, staff, page, acknowledged=acknowledged)
    return Page[AlertRead].model_validate(result, from_attributes=True)


@router.post("/{alert_id}/acknowledge", response_model=AlertRead)
async def acknowledge_alert(alert_id: uuid.UUID, staff: StaffUser, db: DbSession) -> AlertRead:
    """Mark an alert as seen. Safe to call twice."""
    return AlertRead.model_validate(await service.acknowledge(db, staff, alert_id))
