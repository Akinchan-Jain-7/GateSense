import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUser, DbSession, Pagination
from app.models.enums import ResidentType
from app.schemas.common import Page
from app.schemas.user import ResidentCreate, ResidentRead, ResidentUpdate
from app.services import residents as service

router = APIRouter(prefix="/residents", tags=["residents"])


@router.get("", response_model=Page[ResidentRead])
async def list_residents(
    admin: AdminUser,
    db: DbSession,
    page: Pagination,
    flat_id: uuid.UUID | None = None,
    block: str | None = None,
    resident_type: ResidentType | None = None,
    is_active: bool | None = None,
    q: Annotated[str | None, Query(description="Search name, email or phone")] = None,
) -> Page[ResidentRead]:
    result = await service.list_residents(
        db,
        admin,
        page,
        flat_id=flat_id,
        block=block,
        resident_type=resident_type,
        is_active=is_active,
        q=q,
    )
    return Page[ResidentRead].model_validate(result, from_attributes=True)


@router.post("", response_model=ResidentRead, status_code=status.HTTP_201_CREATED)
async def create_resident(body: ResidentCreate, admin: AdminUser, db: DbSession) -> ResidentRead:
    """Creates the resident's login and links them to the flat."""
    return ResidentRead.model_validate(await service.create_resident(db, admin, body))


@router.get("/{resident_id}", response_model=ResidentRead)
async def get_resident(resident_id: uuid.UUID, admin: AdminUser, db: DbSession) -> ResidentRead:
    return ResidentRead.model_validate(await service.get_resident(db, admin, resident_id))


@router.patch("/{resident_id}", response_model=ResidentRead)
async def update_resident(
    resident_id: uuid.UUID, body: ResidentUpdate, admin: AdminUser, db: DbSession
) -> ResidentRead:
    return ResidentRead.model_validate(await service.update_resident(db, admin, resident_id, body))


@router.delete("/{resident_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_resident(resident_id: uuid.UUID, admin: AdminUser, db: DbSession) -> None:
    """Removes the person from the flat; deactivates their login if no flats remain."""
    await service.remove_resident(db, admin, resident_id)
