import uuid

from fastapi import APIRouter

from app.api.deps import AppSettings, CurrentUser, DbSession, Pagination, RedisClient, ResidentUser
from app.models.enums import ApprovalChannel, ApprovalStatus
from app.schemas.common import Page
from app.schemas.visit import ApprovalRead, Decision
from app.services import visitors as service

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("", response_model=Page[ApprovalRead])
async def list_approvals(
    user: CurrentUser, db: DbSession, page: Pagination, status: ApprovalStatus | None = None
) -> Page[ApprovalRead]:
    """Residents: requests for their flats (`status=pending` for the inbox). Staff: all."""
    result = await service.list_approvals(db, user, page, status=status)
    return Page[ApprovalRead](
        items=[service.approval_read(a) for a in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.post("/{approval_id}/decision", response_model=ApprovalRead)
async def decide(
    approval_id: uuid.UUID,
    body: Decision,
    resident: ResidentUser,
    db: DbSession,
    redis: RedisClient,
    settings: AppSettings,
) -> ApprovalRead:
    """Approve or deny a visitor for your flat. Repeating the same answer is fine (200);
    changing it after deciding, or answering after the timeout, is a 409."""
    result = await service.decide_approval(
        db, redis, settings, resident, approval_id, body.decision == "approve", ApprovalChannel.WEB
    )
    return service.approval_read(result.approval)
