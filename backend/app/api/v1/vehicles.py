import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUser, DbSession, Pagination, StaffUser
from app.models.enums import VehicleType
from app.schemas.common import Page
from app.schemas.vehicle import VehicleCreate, VehicleRead, VehicleUpdate
from app.services import vehicles as service

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


@router.get("", response_model=Page[VehicleRead])
async def list_vehicles(
    user: StaffUser,
    db: DbSession,
    page: Pagination,
    flat_id: uuid.UUID | None = None,
    vehicle_type: VehicleType | None = None,
    is_active: bool | None = None,
    q: Annotated[str | None, Query(description="Part of a plate, e.g. AB12")] = None,
) -> Page[VehicleRead]:
    result = await service.list_vehicles(
        db, user, page, flat_id=flat_id, vehicle_type=vehicle_type, is_active=is_active, q=q
    )
    return Page[VehicleRead].model_validate(result, from_attributes=True)


@router.post("", response_model=VehicleRead, status_code=status.HTTP_201_CREATED)
async def create_vehicle(body: VehicleCreate, admin: AdminUser, db: DbSession) -> VehicleRead:
    return VehicleRead.model_validate(await service.create_vehicle(db, admin, body))


@router.get("/{vehicle_id}", response_model=VehicleRead)
async def get_vehicle(vehicle_id: uuid.UUID, user: StaffUser, db: DbSession) -> VehicleRead:
    return VehicleRead.model_validate(await service.get_vehicle(db, user, vehicle_id))


@router.patch("/{vehicle_id}", response_model=VehicleRead)
async def update_vehicle(
    vehicle_id: uuid.UUID, body: VehicleUpdate, admin: AdminUser, db: DbSession
) -> VehicleRead:
    return VehicleRead.model_validate(await service.update_vehicle(db, admin, vehicle_id, body))


@router.delete("/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vehicle(vehicle_id: uuid.UUID, admin: AdminUser, db: DbSession) -> None:
    await service.delete_vehicle(db, admin, vehicle_id)
