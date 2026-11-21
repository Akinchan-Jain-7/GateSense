import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Flat, User
from app.schemas.flat import FlatCreate, FlatUpdate
from app.services import audit
from app.services.db_helpers import get_in_society, integrity_guard
from app.services.pagination import PageRequest, PageResult, paginate


async def list_flats(
    db: AsyncSession,
    actor: User,
    page: PageRequest,
    *,
    block: str | None = None,
    q: str | None = None,
) -> PageResult[Flat]:
    statement = (
        select(Flat).where(Flat.society_id == actor.society_id).order_by(Flat.block, Flat.number)
    )
    if block:
        statement = statement.where(Flat.block == block.upper())
    if q:
        # Lets a guard type "402" or "B-402".
        statement = statement.where((Flat.block + "-" + Flat.number).ilike(f"%{q.strip()}%"))
    return await paginate(db, statement, page)


async def get_flat(db: AsyncSession, actor: User, flat_id: uuid.UUID) -> Flat:
    return await get_in_society(db, Flat, flat_id, actor.society_id)


async def create_flat(db: AsyncSession, actor: User, data: FlatCreate) -> Flat:
    flat = Flat(society_id=actor.society_id, **data.model_dump())
    async with integrity_guard(db, f"Flat {data.block}-{data.number} already exists"):
        db.add(flat)
    audit.record(db, actor, "flat.create", flat.id, audit.snapshot(data.model_dump()))
    await db.commit()
    return flat


async def update_flat(db: AsyncSession, actor: User, flat_id: uuid.UUID, data: FlatUpdate) -> Flat:
    flat = await get_flat(db, actor, flat_id)
    updates = data.changes()
    new_label = f"{updates.get('block', flat.block)}-{updates.get('number', flat.number)}"
    async with integrity_guard(db, f"Flat {new_label} already exists"):
        changes = audit.apply_changes(flat, updates)
    if changes:
        audit.record(db, actor, "flat.update", flat.id, changes)
    await db.commit()
    return flat


async def delete_flat(db: AsyncSession, actor: User, flat_id: uuid.UUID) -> None:
    flat = await get_flat(db, actor, flat_id)
    label = flat.label
    async with integrity_guard(
        db, f"Flat {label} still has residents, vehicles or visit history and can't be deleted"
    ):
        await db.delete(flat)
    audit.record(db, actor, "flat.delete", flat_id, {"label": label})
    await db.commit()
