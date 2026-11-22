"""Numbers for the admin dashboard, computed straight from the visit and gate-event tables.

Everything is one SQL query per figure, grouped in the database, so the cost doesn't grow
with the number of rows sent to Python. Hours and days are in Indian time (IST): "busiest
hour 6 pm" should mean 6 pm at the gate, not 6 pm UTC.

Definitions (also shown in the UI so the numbers can be checked):
- busiest hours: entry-lane reads per hour of the day, residents vs everyone else
- average visit duration: entry to exit, for visits that ended inside the window
- overstay rate: of the visits that entered inside the window, the share that ever went
  past their time limit
- frequent visitors: most visits inside the window
- vehicles inside now: visits that are inside + resident cars whose latest read was at an
  entry lane
- visitor parking: visitor vehicles inside / visitor parking spaces
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Date, and_, cast, distinct, exists, extract, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import Settings
from app.models import Flat, GateEvent, Visit, Visitor, VisitStatusChange
from app.models.enums import LaneDirection, MatchResult, VisitCategory, VisitStatus
from app.schemas.visit import mask_phone
from app.services import society_settings
from app.services.visit_state import INSIDE_STATUSES

IST = ZoneInfo("Asia/Kolkata")
IST_NAME = "Asia/Kolkata"


@dataclass(frozen=True)
class HourCount:
    hour: int  # 0-23, IST
    residents: int
    visitors: int


@dataclass(frozen=True)
class DayCount:
    day: date  # IST
    visits: int


@dataclass(frozen=True)
class CategoryStat:
    category: VisitCategory
    visits: int
    average_minutes: float | None


@dataclass(frozen=True)
class FrequentVisitor:
    visitor_id: uuid.UUID
    name: str
    phone_masked: str
    visits: int
    last_visit_at: datetime
    flats: list[str]


@dataclass(frozen=True)
class Overview:
    days: int
    since: datetime
    visits: int
    average_visit_minutes: float | None
    overstayed_visits: int
    overstay_rate: float | None  # None when no visits entered: 0 % would be misleading
    visitors_inside: int
    residents_inside: int
    visitor_vehicles_inside: int
    visitor_parking_slots: int
    busiest_hours: list[HourCount]
    daily_visits: list[DayCount]
    categories: list[CategoryStat]
    frequent_visitors: list[FrequentVisitor]

    @property
    def vehicles_inside(self) -> int:
        return self.visitors_inside + self.residents_inside


Timestamp = ColumnElement[datetime] | InstrumentedAttribute[datetime | None]


def _ist_hour(column: Timestamp) -> ColumnElement[Any]:
    return extract("hour", func.timezone(IST_NAME, column))


def _ist_day(column: Timestamp) -> ColumnElement[Any]:
    return cast(func.timezone(IST_NAME, column), Date)


def _minutes(start: Timestamp, end: Timestamp) -> ColumnElement[Any]:
    return extract("epoch", end - start) / 60


async def overview(
    db: AsyncSession, settings: Settings, society_id: uuid.UUID, *, now: datetime, days: int
) -> Overview:
    since = now - timedelta(days=days)
    limits = await society_settings.visit_limits(db, settings, society_id)
    in_society = Visit.society_id == society_id

    entered = and_(in_society, Visit.entered_at >= since, Visit.entered_at <= now)
    visits = await db.scalar(select(func.count()).where(entered)) or 0

    finished = and_(in_society, Visit.exited_at >= since, Visit.exited_at <= now)
    average = await db.scalar(
        select(func.avg(_minutes(Visit.entered_at, Visit.exited_at))).where(
            finished, Visit.entered_at.is_not(None)
        )
    )

    went_over = exists().where(
        VisitStatusChange.visit_id == Visit.id,
        VisitStatusChange.to_status == VisitStatus.OVERSTAYED,
    )
    overstayed = await db.scalar(select(func.count()).where(entered, went_over)) or 0

    inside_visits = and_(in_society, Visit.status.in_(INSIDE_STATUSES))
    visitors_inside = await db.scalar(select(func.count()).where(inside_visits)) or 0
    visitor_vehicles = (
        await db.scalar(
            select(func.count()).where(inside_visits, Visit.plate_normalized.is_not(None))
        )
        or 0
    )

    # A resident car is inside when its most recent read was at an entry lane. A car parked
    # at home for a week is normal (reconciliation flags the real gaps, like two entries
    # in a row), so there is no time window here.
    latest = (
        select(GateEvent.direction)
        .where(
            GateEvent.society_id == society_id,
            GateEvent.match_result == MatchResult.RESIDENT,
            GateEvent.captured_at <= now,
        )
        .ext(distinct_on(GateEvent.plate_normalized))
        .order_by(GateEvent.plate_normalized, GateEvent.captured_at.desc())
        .subquery()
    )
    residents_inside = (
        await db.scalar(
            select(func.count())
            .select_from(latest)
            .where(latest.c.direction == LaneDirection.ENTRY)
        )
        or 0
    )

    return Overview(
        days=days,
        since=since,
        visits=visits,
        average_visit_minutes=round(float(average), 1) if average is not None else None,
        overstayed_visits=overstayed,
        overstay_rate=round(overstayed / visits, 4) if visits else None,
        visitors_inside=visitors_inside,
        residents_inside=residents_inside,
        visitor_vehicles_inside=visitor_vehicles,
        visitor_parking_slots=limits.visitor_parking_slots,
        busiest_hours=await _busiest_hours(db, society_id, since, now),
        daily_visits=await _daily_visits(db, society_id, since, now),
        categories=await _categories(db, society_id, since, now),
        frequent_visitors=await _frequent_visitors(db, society_id, since, now),
    )


async def _busiest_hours(
    db: AsyncSession, society_id: uuid.UUID, since: datetime, now: datetime
) -> list[HourCount]:
    hour = _ist_hour(GateEvent.captured_at).label("hour")
    is_resident = GateEvent.match_result == MatchResult.RESIDENT
    rows = await db.execute(
        select(
            hour,
            func.count().filter(is_resident),
            func.count().filter(~is_resident),
        )
        .where(
            GateEvent.society_id == society_id,
            GateEvent.direction == LaneDirection.ENTRY,
            GateEvent.captured_at >= since,
            GateEvent.captured_at <= now,
        )
        .group_by(hour)
    )
    counts = {int(h): (r, v) for h, r, v in rows.all()}
    return [HourCount(h, *counts.get(h, (0, 0))) for h in range(24)]


async def _daily_visits(
    db: AsyncSession, society_id: uuid.UUID, since: datetime, now: datetime
) -> list[DayCount]:
    day = _ist_day(Visit.entered_at).label("day")
    rows = await db.execute(
        select(day, func.count())
        .where(Visit.society_id == society_id, Visit.entered_at >= since, Visit.entered_at <= now)
        .group_by(day)
    )
    counts: dict[date, int] = {d: n for d, n in rows.all()}
    first, last = since.astimezone(IST).date(), now.astimezone(IST).date()
    # Every day in the window, including quiet ones: a gap in a chart looks like missing data.
    return [
        DayCount(first + timedelta(days=i), counts.get(first + timedelta(days=i), 0))
        for i in range((last - first).days + 1)
    ]


async def _categories(
    db: AsyncSession, society_id: uuid.UUID, since: datetime, now: datetime
) -> list[CategoryStat]:
    rows = await db.execute(
        select(
            Visit.category,
            func.count(),
            func.avg(_minutes(Visit.entered_at, Visit.exited_at)),
        )
        .where(Visit.society_id == society_id, Visit.entered_at >= since, Visit.entered_at <= now)
        .group_by(Visit.category)
    )
    found = {c: (n, avg) for c, n, avg in rows.all()}
    return [
        CategoryStat(
            category,
            found.get(category, (0, None))[0],
            round(float(found[category][1]), 1)
            if category in found and found[category][1] is not None
            else None,
        )
        for category in VisitCategory
    ]


async def _frequent_visitors(
    db: AsyncSession, society_id: uuid.UUID, since: datetime, now: datetime, limit: int = 5
) -> list[FrequentVisitor]:
    flat_label = func.concat(Flat.block, "-", Flat.number)
    rows = await db.execute(
        select(
            Visitor.id,
            Visitor.full_name,
            Visitor.phone,
            func.count(Visit.id).label("visits"),
            func.max(Visit.entered_at),
            func.array_agg(distinct(flat_label)),
        )
        .join(Visit, Visit.visitor_id == Visitor.id)
        .join(Flat, Flat.id == Visit.flat_id)
        .where(Visit.society_id == society_id, Visit.entered_at >= since, Visit.entered_at <= now)
        .group_by(Visitor.id)
        .order_by(func.count(Visit.id).desc(), func.max(Visit.entered_at).desc())
        .limit(limit)
    )
    return [
        FrequentVisitor(
            visitor_id=visitor_id,
            name=name,
            phone_masked=mask_phone(phone) or "",
            visits=count,
            last_visit_at=last or since,  # never None: the join requires an entry time
            flats=sorted(flats),
        )
        for visitor_id, name, phone, count, last, flats in rows.all()
    ]
