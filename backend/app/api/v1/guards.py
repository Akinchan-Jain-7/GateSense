import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUser, DbSession, Pagination
from app.schemas.common import Page
from app.schemas.user import GuardCreate, GuardRead, GuardUpdate
from app.services import guards as service

router = APIRouter(prefix="/guards", tags=["guards"])


@router.get("", response_model=Page[GuardRead])
async def list_guards(
    admin: AdminUser,
    db: DbSession,
    page: Pagination,
    is_active: bool | None = None,
    q: Annotated[str | None, Query(description="Search name or email")] = None,
) -> Page[GuardRead]:
    result = await service.list_guards(db, admin, page, q=q, is_active=is_active)
    return Page[GuardRead].model_validate(result, from_attributes=True)


@router.post("", response_model=GuardRead, status_code=status.HTTP_201_CREATED)
async def create_guard(body: GuardCreate, admin: AdminUser, db: DbSession) -> GuardRead:
    return GuardRead.model_validate(await service.create_guard(db, admin, body))


@router.get("/{guard_id}", response_model=GuardRead)
async def get_guard(guard_id: uuid.UUID, admin: AdminUser, db: DbSession) -> GuardRead:
    return GuardRead.model_validate(await service.get_guard(db, admin, guard_id))


@router.patch("/{guard_id}", response_model=GuardRead)
async def update_guard(
    guard_id: uuid.UUID, body: GuardUpdate, admin: AdminUser, db: DbSession
) -> GuardRead:
    return GuardRead.model_validate(await service.update_guard(db, admin, guard_id, body))


@router.delete("/{guard_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_guard(guard_id: uuid.UUID, admin: AdminUser, db: DbSession) -> None:
    """Deactivates the guard (their logins stop at once); the record is kept for history."""
    await service.deactivate_guard(db, admin, guard_id)
