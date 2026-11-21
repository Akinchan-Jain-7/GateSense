"""Resident vehicles. The plate is cleaned and validated before it is saved, so the
gate engine (Phase 2) can match OCR reads against `plate_normalized` directly."""

import uuid

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models import Flat, User, Vehicle
from app.models.enums import VehicleType
from app.schemas.vehicle import VehicleCreate, VehicleUpdate
from app.services import audit
from app.services.db_helpers import get_in_society, integrity_guard
from app.services.errors import NotFoundError
from app.services.pagination import PageRequest, PageResult, paginate
from app.services.plates import clean_plate, normalize_typed_plate


def _with_flat() -> Select[Vehicle]:
    return select(Vehicle).options(joinedload(Vehicle.flat))


async def list_vehicles(
    db: AsyncSession,
    actor: User,
    page: PageRequest,
    *,
    flat_id: uuid.UUID | None = None,
    vehicle_type: VehicleType | None = None,
    is_active: bool | None = None,
    q: str | None = None,
) -> PageResult[Vehicle]:
    statement = (
        _with_flat()
        .where(Vehicle.society_id == actor.society_id)
        .order_by(Vehicle.plate_normalized)
    )
    if flat_id:
        statement = statement.where(Vehicle.flat_id == flat_id)
    if vehicle_type:
        statement = statement.where(Vehicle.vehicle_type == vehicle_type)
    if is_active is not None:
        statement = statement.where(Vehicle.is_active == is_active)
    if q:
        # "ab 12" finds DL01AB1234: search on the cleaned form.
        statement = statement.where(Vehicle.plate_normalized.contains(clean_plate(q)))
    return await paginate(db, statement, page)


async def get_vehicle(db: AsyncSession, actor: User, vehicle_id: uuid.UUID) -> Vehicle:
    vehicle = await db.scalar(
        _with_flat().where(Vehicle.id == vehicle_id, Vehicle.society_id == actor.society_id)
    )
    if vehicle is None:
        raise NotFoundError("Vehicle not found")
    return vehicle


async def create_vehicle(db: AsyncSession, actor: User, data: VehicleCreate) -> Vehicle:
    flat = await get_in_society(db, Flat, data.flat_id, actor.society_id)
    plate = normalize_typed_plate(data.plate)
    vehicle = Vehicle(
        society_id=actor.society_id,
        flat=flat,
        plate_raw=data.plate,
        plate_normalized=plate,
        vehicle_type=data.vehicle_type,
        make_model=data.make_model,
        colour=data.colour,
    )
    async with integrity_guard(db, f"A vehicle with plate {plate} is already registered"):
        db.add(vehicle)
    audit.record(db, actor, "vehicle.create", vehicle.id, audit.snapshot(data.model_dump()))
    await db.commit()
    return vehicle


async def update_vehicle(
    db: AsyncSession, actor: User, vehicle_id: uuid.UUID, data: VehicleUpdate
) -> Vehicle:
    vehicle = await get_vehicle(db, actor, vehicle_id)
    updates = data.changes()
    if "plate" in updates:
        raw = updates.pop("plate")
        updates["plate_normalized"] = normalize_typed_plate(raw)
        updates["plate_raw"] = raw
    if "flat_id" in updates:
        vehicle.flat = await get_in_society(db, Flat, updates["flat_id"], actor.society_id)

    plate = updates.get("plate_normalized", vehicle.plate_normalized)
    async with integrity_guard(db, f"A vehicle with plate {plate} is already registered"):
        changes = audit.apply_changes(vehicle, updates)
    if changes:
        audit.record(db, actor, "vehicle.update", vehicle.id, changes)
    await db.commit()
    return vehicle


async def delete_vehicle(db: AsyncSession, actor: User, vehicle_id: uuid.UUID) -> None:
    """Hard delete: past gate events keep the plate text; their vehicle link becomes NULL."""
    vehicle = await get_vehicle(db, actor, vehicle_id)
    plate = vehicle.plate_normalized
    await db.delete(vehicle)
    audit.record(db, actor, "vehicle.delete", vehicle_id, {"plate": plate})
    await db.commit()
