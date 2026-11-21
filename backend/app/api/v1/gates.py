import uuid

from fastapi import APIRouter, status

from app.api.deps import AdminUser, CurrentDevice, DbSession, Pagination
from app.models import Device
from app.models.enums import LaneDirection
from app.schemas.auth import DeviceIdentity
from app.schemas.common import Page
from app.schemas.gate import (
    DeviceCreate,
    DeviceRead,
    DeviceUpdate,
    DeviceWithKey,
    GateCreate,
    GateRead,
    GateUpdate,
)
from app.services import gates as service

gates_router = APIRouter(prefix="/gates", tags=["gates"])
devices_router = APIRouter(prefix="/devices", tags=["devices"])


def _with_key(device: Device, api_key: str) -> DeviceWithKey:
    return DeviceWithKey(**DeviceRead.model_validate(device).model_dump(), api_key=api_key)


@gates_router.get("", response_model=Page[GateRead])
async def list_gates(
    admin: AdminUser, db: DbSession, page: Pagination, is_active: bool | None = None
) -> Page[GateRead]:
    result = await service.list_gates(db, admin, page, is_active=is_active)
    return Page[GateRead].model_validate(result, from_attributes=True)


@gates_router.post("", response_model=GateRead, status_code=status.HTTP_201_CREATED)
async def create_gate(body: GateCreate, admin: AdminUser, db: DbSession) -> GateRead:
    return GateRead.model_validate(await service.create_gate(db, admin, body))


@gates_router.get("/{gate_id}", response_model=GateRead)
async def get_gate(gate_id: uuid.UUID, admin: AdminUser, db: DbSession) -> GateRead:
    return GateRead.model_validate(await service.get_gate(db, admin, gate_id))


@gates_router.patch("/{gate_id}", response_model=GateRead)
async def update_gate(
    gate_id: uuid.UUID, body: GateUpdate, admin: AdminUser, db: DbSession
) -> GateRead:
    return GateRead.model_validate(await service.update_gate(db, admin, gate_id, body))


@gates_router.delete("/{gate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_gate(gate_id: uuid.UUID, admin: AdminUser, db: DbSession) -> None:
    """Only works for a gate without devices (otherwise 409; deactivate it instead)."""
    await service.delete_gate(db, admin, gate_id)


# Declared before "/{device_id}" so "me" isn't read as a device id.
@devices_router.get("/me", response_model=DeviceIdentity)
async def device_me(device: CurrentDevice) -> DeviceIdentity:
    """For cameras: check that an API key works. Send it in the `X-Device-Key` header."""
    return DeviceIdentity.model_validate(device)


@devices_router.get("", response_model=Page[DeviceRead])
async def list_devices(
    admin: AdminUser,
    db: DbSession,
    page: Pagination,
    gate_id: uuid.UUID | None = None,
    direction: LaneDirection | None = None,
    is_active: bool | None = None,
) -> Page[DeviceRead]:
    result = await service.list_devices(
        db, admin, page, gate_id=gate_id, direction=direction, is_active=is_active
    )
    return Page[DeviceRead].model_validate(result, from_attributes=True)


@devices_router.post("", response_model=DeviceWithKey, status_code=status.HTTP_201_CREATED)
async def create_device(body: DeviceCreate, admin: AdminUser, db: DbSession) -> DeviceWithKey:
    """Registers a camera and returns its API key. **The key is shown only once.**"""
    device, api_key = await service.create_device(db, admin, body)
    return _with_key(device, api_key)


@devices_router.get("/{device_id}", response_model=DeviceRead)
async def get_device(device_id: uuid.UUID, admin: AdminUser, db: DbSession) -> DeviceRead:
    return DeviceRead.model_validate(await service.get_device(db, admin, device_id))


@devices_router.post("/{device_id}/rotate-key", response_model=DeviceWithKey)
async def rotate_device_key(device_id: uuid.UUID, admin: AdminUser, db: DbSession) -> DeviceWithKey:
    """Issues a new API key; the old key stops working immediately."""
    device, api_key = await service.rotate_device_key(db, admin, device_id)
    return _with_key(device, api_key)


@devices_router.patch("/{device_id}", response_model=DeviceRead)
async def update_device(
    device_id: uuid.UUID, body: DeviceUpdate, admin: AdminUser, db: DbSession
) -> DeviceRead:
    return DeviceRead.model_validate(await service.update_device(db, admin, device_id, body))


@devices_router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(device_id: uuid.UUID, admin: AdminUser, db: DbSession) -> None:
    """Only works for a device that never sent an event (otherwise 409; deactivate it)."""
    await service.delete_device(db, admin, device_id)
