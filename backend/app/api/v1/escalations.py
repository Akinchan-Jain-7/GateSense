import uuid

from fastapi import APIRouter

from app.api.deps import AdminUser, AppSettings, DbSession, Pagination, RedisClient, StaffUser
from app.models.enums import EscalationTaskStatus
from app.schemas.common import Page
from app.schemas.escalation import EscalationRead, EscalationResolution, ReconciliationFlagRead
from app.services import escalation, reconciliation

router = APIRouter(tags=["escalation"])


@router.get("/escalations", response_model=Page[EscalationRead])
async def list_escalations(
    staff: StaffUser, db: DbSession, page: Pagination, status: EscalationTaskStatus | None = None
) -> Page[EscalationRead]:
    """ "Call the resident" tasks for visits 60+ minutes over their limit (`status=open`)."""
    result = await escalation.list_tasks(db, staff, page, status=status)
    return Page[EscalationRead](
        items=[escalation.task_read(t) for t in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.post("/escalations/{task_id}/resolve", response_model=EscalationRead)
async def resolve_escalation(
    task_id: uuid.UUID,
    body: EscalationResolution,
    staff: StaffUser,
    db: DbSession,
    redis: RedisClient,
    settings: AppSettings,
) -> EscalationRead:
    """Record what happened. `vehicle_left` also closes the visit."""
    task = await escalation.resolve_task(
        db, redis, settings, staff, task_id, body.outcome, body.notes
    )
    return escalation.task_read(task)


@router.get("/reconciliation", response_model=Page[ReconciliationFlagRead])
async def list_reconciliation_flags(
    admin: AdminUser, db: DbSession, page: Pagination, resolved: bool | None = None
) -> Page[ReconciliationFlagRead]:
    """What the nightly reconciliation found (`resolved=false` for open items)."""
    result = await reconciliation.list_flags(db, admin, page, resolved=resolved)
    return Page[ReconciliationFlagRead].model_validate(result, from_attributes=True)


@router.post("/reconciliation/{flag_id}/resolve", response_model=ReconciliationFlagRead)
async def resolve_reconciliation_flag(
    flag_id: uuid.UUID, admin: AdminUser, db: DbSession
) -> ReconciliationFlagRead:
    flag = await reconciliation.resolve_flag(db, admin, flag_id)
    return ReconciliationFlagRead.model_validate(flag, from_attributes=True)
