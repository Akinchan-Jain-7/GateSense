import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, WatchlistEntry
from app.schemas.vehicle import WatchlistCreate, WatchlistUpdate
from app.services import audit
from app.services.db_helpers import get_in_society, integrity_guard
from app.services.pagination import PageRequest, PageResult, paginate
from app.services.plates import clean_plate, normalize_typed_plate


async def list_entries(
    db: AsyncSession,
    actor: User,
    page: PageRequest,
    *,
    is_active: bool | None = None,
    q: str | None = None,
) -> PageResult[WatchlistEntry]:
    statement = (
        select(WatchlistEntry)
        .where(WatchlistEntry.society_id == actor.society_id)
        .order_by(WatchlistEntry.created_at.desc())
    )
    if is_active is not None:
        statement = statement.where(WatchlistEntry.is_active == is_active)
    if q:
        statement = statement.where(WatchlistEntry.plate_normalized.contains(clean_plate(q)))
    return await paginate(db, statement, page)


async def get_entry(db: AsyncSession, actor: User, entry_id: uuid.UUID) -> WatchlistEntry:
    return await get_in_society(db, WatchlistEntry, entry_id, actor.society_id)


async def create_entry(db: AsyncSession, actor: User, data: WatchlistCreate) -> WatchlistEntry:
    plate = normalize_typed_plate(data.plate)
    entry = WatchlistEntry(
        society_id=actor.society_id,
        plate_normalized=plate,
        reason=data.reason,
        added_by_id=actor.id,
    )
    async with integrity_guard(db, f"{plate} is already on the watchlist"):
        db.add(entry)
    audit.record(db, actor, "watchlist.create", entry.id, {"plate": plate, "reason": data.reason})
    await db.commit()
    return entry


async def update_entry(
    db: AsyncSession, actor: User, entry_id: uuid.UUID, data: WatchlistUpdate
) -> WatchlistEntry:
    entry = await get_entry(db, actor, entry_id)
    changes = audit.apply_changes(entry, data.changes())
    if changes:
        audit.record(db, actor, "watchlist.update", entry.id, changes)
    await db.commit()
    return entry


async def delete_entry(db: AsyncSession, actor: User, entry_id: uuid.UUID) -> None:
    entry = await get_entry(db, actor, entry_id)
    plate = entry.plate_normalized
    await db.delete(entry)
    audit.record(db, actor, "watchlist.delete", entry_id, {"plate": plate})
    await db.commit()
