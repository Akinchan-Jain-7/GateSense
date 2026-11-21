import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import (
    AppSettings,
    CurrentUser,
    DbSession,
    Jobs,
    Pagination,
    RedisClient,
    StaffUser,
)
from app.models.enums import VisitStatus, VisitTrigger
from app.schemas.common import Page
from app.schemas.visit import Decision, VisitorRegistration, VisitRead, VisitRegistered
from app.services import visitors as service

router = APIRouter(prefix="/visits", tags=["visits"])


@router.post("", response_model=VisitRegistered, status_code=status.HTTP_201_CREATED)
async def register_visitor(
    body: VisitorRegistration,
    staff: StaffUser,
    db: DbSession,
    redis: RedisClient,
    jobs: Jobs,
    settings: AppSettings,
) -> VisitRegistered:
    """The guard registers a visitor. The flat's residents are asked to approve (web push +
    Telegram); after `approval_timeout_seconds` the guard decides with `/decision`.

    Pass `gate_event_id` (the unknown entry read) and the car is admitted the moment a
    resident approves."""
    result = await service.register_visitor(db, redis, jobs, settings, staff, body)
    return VisitRegistered(
        visit=service.visit_read(result.visit), approval=service.approval_read(result.approval)
    )


@router.get("", response_model=Page[VisitRead])
async def list_visits(
    user: CurrentUser,
    db: DbSession,
    page: Pagination,
    status: VisitStatus | None = None,
    inside: Annotated[bool | None, Query(description="Only visits whose vehicle is inside")] = None,
    flat_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(description="Visitor name or part of a plate")] = None,
) -> Page[VisitRead]:
    """Staff see every visit; residents see their own flats' visits. Newest first."""
    result = await service.list_visits(
        db, user, page, status=status, inside=inside, flat_id=flat_id, q=q
    )
    return Page[VisitRead](
        items=[service.visit_read(v) for v in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.get("/{visit_id}", response_model=VisitRead)
async def get_visit(visit_id: uuid.UUID, user: CurrentUser, db: DbSession) -> VisitRead:
    return service.visit_read(await service.get_visit(db, user, visit_id))


@router.post("/{visit_id}/decision", response_model=VisitRead)
async def guard_decision(
    visit_id: uuid.UUID,
    body: Decision,
    staff: StaffUser,
    db: DbSession,
    redis: RedisClient,
    settings: AppSettings,
) -> VisitRead:
    """The guard approves or denies after the residents' time ran out (409 before that)."""
    visit = await service.guard_decide(
        db, redis, settings, staff, visit_id, body.decision == "approve"
    )
    return service.visit_read(visit)


@router.post("/{visit_id}/enter", response_model=VisitRead)
async def mark_entered(
    visit_id: uuid.UUID, staff: StaffUser, db: DbSession, redis: RedisClient, settings: AppSettings
) -> VisitRead:
    """Mark an approved visitor as inside by hand (walk-in, or the camera missed it)."""
    return service.visit_read(
        await service.manual_move(db, redis, settings, staff, visit_id, VisitTrigger.ENTER)
    )


@router.post("/{visit_id}/exit", response_model=VisitRead)
async def mark_exited(
    visit_id: uuid.UUID, staff: StaffUser, db: DbSession, redis: RedisClient, settings: AppSettings
) -> VisitRead:
    """Mark a visitor as gone by hand."""
    return service.visit_read(
        await service.manual_move(db, redis, settings, staff, visit_id, VisitTrigger.EXIT)
    )
