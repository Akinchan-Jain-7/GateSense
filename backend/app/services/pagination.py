"""Offset pagination: run a filtered query twice, once for the page and once for the total."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class PageRequest:
    limit: int
    offset: int


@dataclass(frozen=True)
class PageResult[T]:
    items: Sequence[T]
    total: int
    limit: int
    offset: int


async def paginate[T](db: AsyncSession, statement: Select[T], page: PageRequest) -> PageResult[T]:
    # Count over the same filters, without ORDER BY / eager loads (they don't change it).
    count_statement: Select[Any] = select(func.count()).select_from(
        statement.order_by(None).subquery()
    )
    total = await db.scalar(count_statement) or 0
    rows = await db.scalars(statement.limit(page.limit).offset(page.offset))
    return PageResult(items=rows.unique().all(), total=total, limit=page.limit, offset=page.offset)
