"""Small database helpers shared by the services."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.errors import ConflictError, NotFoundError


class SocietyScoped(Protocol):
    """Any model with a `society_id` column."""

    @property
    def society_id(self) -> uuid.UUID: ...


async def get_in_society[M: SocietyScoped](
    db: AsyncSession, model: type[M], record_id: uuid.UUID, society_id: uuid.UUID
) -> M:
    """Load a record by id, but only if it belongs to the caller's society.

    A record from another society gets the same 404 as a missing one, so ids from
    other societies can't even be confirmed to exist.
    """
    record = await db.get(model, record_id)
    if record is None or record.society_id != society_id:
        raise NotFoundError(f"{model.__name__} not found")
    return record


@asynccontextmanager
async def integrity_guard(db: AsyncSession, message: str) -> AsyncIterator[None]:
    """Run writes in a savepoint and turn a database constraint violation into a 409.

    The database's UNIQUE and FOREIGN KEY constraints are the real source of truth (they
    also hold under concurrent requests); we just translate their error into a clear
    message. Only the savepoint is rolled back, so the session stays usable.
    """
    try:
        async with db.begin_nested():
            yield
    except IntegrityError as exc:
        raise ConflictError(message) from exc
