import uuid

from fastapi import APIRouter, status

from app.api.deps import (
    AppSettings,
    CurrentUser,
    DbSession,
    Pagination,
    RedisClient,
    ResidentUser,
    StaffUser,
)
from app.schemas.common import Page
from app.schemas.guest_pass import CodeRedemption, GuestPassCreate, GuestPassCreated, GuestPassRead
from app.schemas.visit import VisitRead
from app.services import guest_passes as service
from app.services import visitors

router = APIRouter(prefix="/guest-passes", tags=["guest passes"])


@router.post("", response_model=GuestPassCreated, status_code=status.HTTP_201_CREATED)
async def create_guest_pass(
    body: GuestPassCreate, resident: ResidentUser, db: DbSession, settings: AppSettings
) -> GuestPassCreated:
    """Pre-approve a guest by plate (the camera lets them in) and/or with a one-time code
    (shown only in this response)."""
    guest_pass, code = await service.create_pass(db, settings, resident, body)
    return GuestPassCreated(
        guest_pass=GuestPassRead.model_validate(guest_pass, from_attributes=True), code=code
    )


@router.get("", response_model=Page[GuestPassRead])
async def list_guest_passes(
    user: CurrentUser, db: DbSession, page: Pagination, active: bool | None = None
) -> Page[GuestPassRead]:
    """Residents: their flats' passes. Staff: all. `active=true`: usable right now."""
    result = await service.list_passes(db, user, page, active=active)
    return Page[GuestPassRead].model_validate(result, from_attributes=True)


@router.post("/{pass_id}/revoke", response_model=GuestPassRead)
async def revoke_guest_pass(
    pass_id: uuid.UUID, resident: ResidentUser, db: DbSession
) -> GuestPassRead:
    return GuestPassRead.model_validate(
        await service.revoke_pass(db, resident, pass_id), from_attributes=True
    )


@router.post("/redeem", response_model=VisitRead, status_code=status.HTTP_201_CREATED)
async def redeem_code(
    body: CodeRedemption, staff: StaffUser, db: DbSession, redis: RedisClient, settings: AppSettings
) -> VisitRead:
    """The guard types the code a guest shows: the visit is created and marked inside."""
    visit = await service.redeem_code(db, settings, staff, body.code, body.plate)
    visit = await visitors.load_visit(db, visit.id)
    await visitors.publish_visit(redis, db, visit, "visit.updated")
    return visitors.visit_read(visit)
