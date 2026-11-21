import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUser, DbSession, Pagination, StaffUser
from app.schemas.common import Page
from app.schemas.flat import FlatCreate, FlatRead, FlatUpdate
from app.services import flats as service

router = APIRouter(prefix="/flats", tags=["flats"])


@router.get("", response_model=Page[FlatRead])
async def list_flats(
    user: StaffUser,
    db: DbSession,
    page: Pagination,
    block: Annotated[str | None, Query(description="e.g. B")] = None,
    q: Annotated[str | None, Query(description="Search the label, e.g. 402 or B-402")] = None,
) -> Page[FlatRead]:
    result = await service.list_flats(db, user, page, block=block, q=q)
    return Page[FlatRead].model_validate(result, from_attributes=True)


@router.post("", response_model=FlatRead, status_code=status.HTTP_201_CREATED)
async def create_flat(body: FlatCreate, admin: AdminUser, db: DbSession) -> FlatRead:
    return FlatRead.model_validate(await service.create_flat(db, admin, body))


@router.get("/{flat_id}", response_model=FlatRead)
async def get_flat(flat_id: uuid.UUID, user: StaffUser, db: DbSession) -> FlatRead:
    return FlatRead.model_validate(await service.get_flat(db, user, flat_id))


@router.patch("/{flat_id}", response_model=FlatRead)
async def update_flat(
    flat_id: uuid.UUID, body: FlatUpdate, admin: AdminUser, db: DbSession
) -> FlatRead:
    return FlatRead.model_validate(await service.update_flat(db, admin, flat_id, body))


@router.delete("/{flat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_flat(flat_id: uuid.UUID, admin: AdminUser, db: DbSession) -> None:
    """Only works for a flat with no residents, vehicles or history (otherwise 409)."""
    await service.delete_flat(db, admin, flat_id)
