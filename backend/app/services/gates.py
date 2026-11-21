"""Gates and their devices (one camera per lane).

A device's API key is generated here and returned once; only its hash is stored.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager

from app.core.security import generate_device_key, hash_api_key
from app.models import Device, Gate, User
from app.models.enums import LaneDirection
from app.schemas.gate import DeviceCreate, DeviceUpdate, GateCreate, GateUpdate
from app.services import audit
from app.services.db_helpers import get_in_society, integrity_guard
from app.services.errors import AuthenticationError, NotFoundError
from app.services.pagination import PageRequest, PageResult, paginate

_GATE_IN_USE = "Gate '{}' has devices and can't be deleted; deactivate it instead"
_DEVICE_IN_USE = "Device '{}' has sent gate events and can't be deleted; deactivate it instead"

# --- Gates --------------------------------------------------------------------


async def list_gates(
    db: AsyncSession, actor: User, page: PageRequest, *, is_active: bool | None = None
) -> PageResult[Gate]:
    statement = select(Gate).where(Gate.society_id == actor.society_id).order_by(Gate.name)
    if is_active is not None:
        statement = statement.where(Gate.is_active == is_active)
    return await paginate(db, statement, page)


async def get_gate(db: AsyncSession, actor: User, gate_id: uuid.UUID) -> Gate:
    return await get_in_society(db, Gate, gate_id, actor.society_id)


async def create_gate(db: AsyncSession, actor: User, data: GateCreate) -> Gate:
    gate = Gate(society_id=actor.society_id, **data.model_dump())
    db.add(gate)
    await db.flush()
    audit.record(db, actor, "gate.create", gate.id, audit.snapshot(data.model_dump()))
    await db.commit()
    return gate


async def update_gate(db: AsyncSession, actor: User, gate_id: uuid.UUID, data: GateUpdate) -> Gate:
    gate = await get_gate(db, actor, gate_id)
    changes = audit.apply_changes(gate, data.changes())
    if changes:
        audit.record(db, actor, "gate.update", gate.id, changes)
    await db.commit()
    return gate


async def delete_gate(db: AsyncSession, actor: User, gate_id: uuid.UUID) -> None:
    gate = await get_gate(db, actor, gate_id)
    name = gate.name
    async with integrity_guard(db, _GATE_IN_USE.format(name)):
        await db.delete(gate)
    audit.record(db, actor, "gate.delete", gate_id, {"name": name})
    await db.commit()


# --- Devices ------------------------------------------------------------------


async def list_devices(
    db: AsyncSession,
    actor: User,
    page: PageRequest,
    *,
    gate_id: uuid.UUID | None = None,
    direction: LaneDirection | None = None,
    is_active: bool | None = None,
) -> PageResult[Device]:
    statement = (
        select(Device)
        .join(Device.gate)
        .where(Gate.society_id == actor.society_id)
        .order_by(Gate.name, Device.name)
    )
    if gate_id:
        statement = statement.where(Device.gate_id == gate_id)
    if direction:
        statement = statement.where(Device.direction == direction)
    if is_active is not None:
        statement = statement.where(Device.is_active == is_active)
    return await paginate(db, statement, page)


async def get_device(db: AsyncSession, actor: User, device_id: uuid.UUID) -> Device:
    device = await db.scalar(
        select(Device)
        .join(Device.gate)
        .where(Device.id == device_id, Gate.society_id == actor.society_id)
    )
    if device is None:
        raise NotFoundError("Device not found")
    return device


async def create_device(db: AsyncSession, actor: User, data: DeviceCreate) -> tuple[Device, str]:
    """Returns the device and its plaintext API key (the only time it's available)."""
    await get_gate(db, actor, data.gate_id)
    key = generate_device_key()
    device = Device(
        gate_id=data.gate_id,
        name=data.name,
        direction=data.direction,
        api_key_hash=key.hash,
        api_key_prefix=key.prefix,
    )
    db.add(device)
    await db.flush()
    audit.record(db, actor, "device.create", device.id, audit.snapshot(data.model_dump()))
    await db.commit()
    return device, key.plaintext


async def rotate_device_key(
    db: AsyncSession, actor: User, device_id: uuid.UUID
) -> tuple[Device, str]:
    """Issue a new key; the old one stops working immediately."""
    device = await get_device(db, actor, device_id)
    key = generate_device_key()
    device.api_key_hash = key.hash
    device.api_key_prefix = key.prefix
    audit.record(db, actor, "device.rotate_key", device.id, {"new_prefix": key.prefix})
    await db.commit()
    return device, key.plaintext


async def update_device(
    db: AsyncSession, actor: User, device_id: uuid.UUID, data: DeviceUpdate
) -> Device:
    device = await get_device(db, actor, device_id)
    changes = audit.apply_changes(device, data.changes())
    if changes:
        audit.record(db, actor, "device.update", device.id, changes)
    await db.commit()
    return device


async def delete_device(db: AsyncSession, actor: User, device_id: uuid.UUID) -> None:
    device = await get_device(db, actor, device_id)
    name = device.name
    async with integrity_guard(db, _DEVICE_IN_USE.format(name)):
        await db.delete(device)
    audit.record(db, actor, "device.delete", device_id, {"name": name})
    await db.commit()


async def authenticate_device(db: AsyncSession, api_key: str) -> Device:
    """Find the active device for an API key (sent by cameras in `X-Device-Key`).

    The device's gate is loaded too (`device.gate.society_id` says whose event it is).
    """
    device = await db.scalar(
        select(Device)
        .join(Device.gate)
        .options(contains_eager(Device.gate))
        .where(
            Device.api_key_hash == hash_api_key(api_key),
            Device.is_active.is_(True),
            Gate.is_active.is_(True),
        )
    )
    if device is None:
        raise AuthenticationError("Invalid or inactive device API key")
    device.last_seen_at = datetime.now(UTC)
    await db.commit()
    return device
