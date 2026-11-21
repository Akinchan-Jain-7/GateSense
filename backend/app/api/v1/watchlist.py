import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUser, DbSession, Pagination
from app.schemas.common import Page
from app.schemas.vehicle import WatchlistCreate, WatchlistRead, WatchlistUpdate
from app.services import watchlist as service

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("", response_model=Page[WatchlistRead])
async def list_entries(
    admin: AdminUser,
    db: DbSession,
    page: Pagination,
    is_active: bool | None = None,
    q: Annotated[str | None, Query(description="Part of a plate")] = None,
) -> Page[WatchlistRead]:
    result = await service.list_entries(db, admin, page, is_active=is_active, q=q)
    return Page[WatchlistRead].model_validate(result, from_attributes=True)


@router.post("", response_model=WatchlistRead, status_code=status.HTTP_201_CREATED)
async def create_entry(body: WatchlistCreate, admin: AdminUser, db: DbSession) -> WatchlistRead:
    return WatchlistRead.model_validate(await service.create_entry(db, admin, body))


@router.get("/{entry_id}", response_model=WatchlistRead)
async def get_entry(entry_id: uuid.UUID, admin: AdminUser, db: DbSession) -> WatchlistRead:
    return WatchlistRead.model_validate(await service.get_entry(db, admin, entry_id))


@router.patch("/{entry_id}", response_model=WatchlistRead)
async def update_entry(
    entry_id: uuid.UUID, body: WatchlistUpdate, admin: AdminUser, db: DbSession
) -> WatchlistRead:
    return WatchlistRead.model_validate(await service.update_entry(db, admin, entry_id, body))


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(entry_id: uuid.UUID, admin: AdminUser, db: DbSession) -> None:
    await service.delete_entry(db, admin, entry_id)
