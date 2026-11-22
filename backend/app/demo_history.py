"""Past activity for the demo: two weeks of visits and gate reads, so the dashboard has a
story to tell the moment the demo starts.

This is *made-up demo data*, created by a fixed random seed. It is never used as a
measured result anywhere: the README's numbers come from real runs (see anpr/eval and
docs/performance.md). Everything here is closed (every visit has exited), so it never
triggers the escalation ladder or sends emails.

The shapes are realistic on purpose: deliveries peak at lunch and dinner, cabs in the
morning and late evening, guests in the evening, residents leave in the morning and come
back at night. A few visits run past their time limit so the overstay figures aren't zero.
"""

import hashlib
import random
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Alert,
    Approval,
    EscalationTask,
    GateEvent,
    Notification,
    Visit,
    Visitor,
    VisitStatusChange,
)
from app.models.enums import (
    AlertKind,
    AlertSeverity,
    ApprovalChannel,
    ApprovalStatus,
    EscalationTaskStatus,
    LaneDirection,
    MatchResult,
    NotificationChannel,
    NotificationStatus,
    ReviewReason,
    VisitCategory,
    VisitStatus,
    VisitTrigger,
)
from app.services.society_settings import VisitLimits

IST = ZoneInfo("Asia/Kolkata")

DELIVERY_RIDERS = [
    ("Rahul Kumar", "Swiggy order"),
    ("Imran Khan", "Zomato order"),
    ("Sunil Yadav", "Blinkit delivery"),
    ("Deepak Chauhan", "Amazon parcel"),
    ("Mohit Saini", "Flipkart parcel"),
    ("Arjun Rawat", "Zepto delivery"),
    ("Salman Ali", "BigBasket groceries"),
    ("Vikas Pal", "Swiggy Instamart"),
]
CAB_DRIVERS = [
    ("Rajesh Tomar", "Uber pickup"),
    ("Sanjay Bhati", "Ola pickup"),
    ("Pradeep Nagar", "Uber drop"),
    ("Mukesh Kumar", "Rapido pickup"),
    ("Naveen Sharma", "Ola drop"),
    ("Harish Rana", "Uber pickup"),
]
SERVICE_PEOPLE = [
    ("Ravi Electricals", "Electrician: kitchen wiring"),
    ("Ashok Plumbing", "Plumber: bathroom leak"),
    ("Manoj (Urban Company)", "AC service"),
    ("Shiv Pest Control", "Pest control"),
    ("Kamal Carpenter", "Wardrobe repair"),
    ("Aqua RO Care", "Water purifier service"),
]
GUEST_FIRST = [
    "Amit",
    "Sneha",
    "Rohan",
    "Nisha",
    "Varun",
    "Tanvi",
    "Kunal",
    "Ritu",
    "Siddharth",
    "Payal",
    "Gaurav",
    "Swati",
    "Nikhil",
    "Divya",
    "Manish",
    "Komal",
    "Abhishek",
    "Jyoti",
    "Tarun",
    "Megha",
]
GUEST_LAST = ["Gupta", "Verma", "Agarwal", "Malhotra", "Bansal", "Kapoor", "Joshi", "Chopra"]
GUEST_PURPOSES = [
    "Family visit",
    "Friends for dinner",
    "Birthday party",
    "Weekend stay",
    "Tuition",
    "Visiting parents",
]

# Relative traffic per hour of the day (IST), index = hour.
DELIVERY_HOURS = [0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 3, 4, 7, 8, 6, 3, 3, 3, 4, 7, 9, 8, 5, 2]
CAB_HOURS = [1, 0, 0, 0, 0, 1, 2, 5, 7, 6, 3, 2, 2, 2, 2, 2, 3, 4, 6, 6, 5, 5, 4, 2]
GUEST_HOURS = [0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 4, 3, 3, 3, 4, 6, 8, 8, 6, 3, 1, 0]
SERVICE_HOURS = [0, 0, 0, 0, 0, 0, 0, 0, 0, 4, 6, 6, 4, 3, 5, 5, 4, 2, 0, 0, 0, 0, 0, 0]
RESIDENT_OUT_HOURS = [0, 0, 0, 0, 0, 0, 1, 4, 8, 8, 5, 3, 2, 2, 2, 2, 1, 1, 1, 1, 0, 0, 0, 0]
RESIDENT_IN_HOURS = [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 4, 6, 8, 8, 6, 4, 2]


@dataclass(frozen=True)
class Lane:
    gate_id: uuid.UUID
    device_id: uuid.UUID


@dataclass(frozen=True)
class GateLanes:
    """The entry and exit cameras of one gate."""

    entry: Lane
    exit: Lane


@dataclass(frozen=True)
class ResidentCar:
    vehicle_id: uuid.UUID
    plate_raw: str
    plate: str


@dataclass(frozen=True)
class FlatContacts:
    flat_id: uuid.UUID
    resident_ids: list[uuid.UUID]


@dataclass
class HistorySummary:
    visits: int = 0
    gate_events: int = 0


@dataclass
class _Person:
    name: str
    phone: str
    purpose: str
    plate: str | None
    visitor: Visitor | None = None


@dataclass
class _Builder:
    db: AsyncSession
    society_id: uuid.UUID
    rng: random.Random
    now: datetime
    summary: HistorySummary = field(default_factory=HistorySummary)
    # Visits and gate events point at each other, so events are inserted after the visits
    # and the visits' entry/exit links are filled in last.
    events: list[GateEvent] = field(default_factory=list)
    status_changes: list[VisitStatusChange] = field(default_factory=list)
    others: list[object] = field(default_factory=list)  # rows that need visits/events first
    last_read: dict[str, GateEvent] = field(default_factory=dict)  # resident plate -> read
    links: list[tuple[Visit, GateEvent, GateEvent | None]] = field(default_factory=list)

    def event(
        self,
        lane: Lane,
        direction: LaneDirection,
        plate_raw: str,
        plate: str,
        at: datetime,
        match: MatchResult,
        *,
        vehicle_id: uuid.UUID | None = None,
        visit_id: uuid.UUID | None = None,
        paired_event_id: uuid.UUID | None = None,
    ) -> GateEvent:
        event_id = uuid.uuid4()
        event = GateEvent(
            id=event_id,
            society_id=self.society_id,
            gate_id=lane.gate_id,
            device_id=lane.device_id,
            direction=direction,
            plate_raw=plate_raw,
            plate_normalized=plate,
            ocr_fixes=0,
            confidence=round(self.rng.uniform(0.86, 0.99), 3),
            captured_at=at,
            received_at=at + timedelta(milliseconds=self.rng.randrange(150, 900)),
            event_hash=hashlib.sha256(f"demo-history:{event_id}".encode()).hexdigest(),
            match_result=match,
            vehicle_id=vehicle_id,
            visit_id=visit_id,
            paired_event_id=paired_event_id,
        )
        self.events.append(event)
        self.summary.gate_events += 1
        if match == MatchResult.RESIDENT:
            self.last_read[plate] = event
        return event

    def at(self, day: date, weights: list[int]) -> datetime:
        hour = self.rng.choices(range(24), weights=weights)[0]
        return datetime(day.year, day.month, day.day, hour, self.rng.randrange(60), tzinfo=IST)


def _phone(rng: random.Random) -> str:
    return f"+91{rng.choice('6789')}{rng.randrange(10**8, 10**9)}"


def _people(
    rng: random.Random, names: list[tuple[str, str]], plate_for: dict[str, str | None]
) -> list[_Person]:
    return [_Person(name, _phone(rng), purpose, plate_for[name]) for name, purpose in names]


class PlateMaker(Protocol):
    """`make_plate(two_wheeler=...)` returns a fresh, unused normalised plate."""

    def __call__(self, *, two_wheeler: bool) -> str: ...


async def add_history(
    db: AsyncSession,
    *,
    society_id: uuid.UUID,
    rng: random.Random,
    now: datetime,
    days: int,
    limits: VisitLimits,
    flats: list[FlatContacts],
    guard_ids: list[uuid.UUID],
    residents_cars: list[ResidentCar],
    main_gate: GateLanes,
    service_gate: GateLanes,
    make_plate: PlateMaker,
    live: bool = False,
    focus_flat: FlatContacts | None = None,
) -> HistorySummary:
    """Add `days` days of closed visits and resident movements ending at `now`.

    With `live`, also set up a believable "right now" at the gate (see _current_state)."""
    b = _Builder(db, society_id, rng, now)
    today = now.astimezone(IST).date()
    first_day = today - timedelta(days=days)

    riders = _people(
        rng, DELIVERY_RIDERS, {n: make_plate(two_wheeler=True) for n, _ in DELIVERY_RIDERS}
    )
    drivers = _people(rng, CAB_DRIVERS, {n: make_plate(two_wheeler=False) for n, _ in CAB_DRIVERS})
    service = _people(
        rng,
        SERVICE_PEOPLE,
        {
            n: make_plate(two_wheeler=True) if rng.random() < 0.6 else None
            for n, _ in SERVICE_PEOPLE
        },
    )
    guests = [
        _Person(
            f"{rng.choice(GUEST_FIRST)} {rng.choice(GUEST_LAST)}",
            _phone(rng),
            rng.choice(GUEST_PURPOSES),
            make_plate(two_wheeler=False) if rng.random() < 0.75 else None,
        )
        for _ in range(28)
    ]

    for offset in range(days + 1):
        day = first_day + timedelta(days=offset)
        weekend = day.weekday() >= 5
        plan = [
            (VisitCategory.DELIVERY, riders, rng.randint(9, 15), DELIVERY_HOURS),
            (VisitCategory.CAB, drivers, rng.randint(3, 7), CAB_HOURS),
            (
                VisitCategory.GUEST,
                guests,
                rng.randint(6, 11) if weekend else rng.randint(2, 6),
                GUEST_HOURS,
            ),
            (
                VisitCategory.SERVICE,
                service,
                0 if day.weekday() == 6 else rng.randint(0, 3),
                SERVICE_HOURS,
            ),
        ]
        for category, pool, count, hours in plan:
            for _ in range(count):
                person = rng.choice(
                    pool[:6] if category == VisitCategory.GUEST and rng.random() < 0.4 else pool
                )
                lanes = (
                    service_gate
                    if category in (VisitCategory.DELIVERY, VisitCategory.SERVICE)
                    and rng.random() < 0.6
                    else main_gate
                )
                _visit(
                    b,
                    person,
                    category,
                    b.at(day, hours),
                    limits,
                    rng.choice(flats),
                    guard_ids,
                    lanes,
                )

    _resident_movements(b, residents_cars, first_day, days, main_gate, service_gate)
    if live:
        _current_state(
            b, limits, flats, guard_ids, residents_cars, main_gate, make_plate, guests, focus_flat
        )
    await db.flush()  # visitors, visits and approvals first
    db.add_all(b.status_changes)
    db.add_all(b.events)
    await db.flush()
    db.add_all(b.others)
    await db.flush()
    for visit, entry, leave in b.links:
        visit.entry_event_id = entry.id
        visit.exit_event_id = leave.id if leave is not None else None
    return b.summary


def _visit(
    b: _Builder,
    person: _Person,
    category: VisitCategory,
    entered_at: datetime,
    limits: VisitLimits,
    flat: FlatContacts,
    guard_ids: list[uuid.UUID],
    lanes: GateLanes,
) -> None:
    rng = b.rng
    if person.visitor is None:
        person.visitor = Visitor(
            id=uuid.uuid4(), society_id=b.society_id, full_name=person.name, phone=person.phone
        )
        b.db.add(person.visitor)

    duration = None
    if category == VisitCategory.SERVICE:
        duration = rng.choice([60, 90, 120])
        limit = timedelta(minutes=duration)
    else:
        limit = limits.for_category(category)
    usual = {
        VisitCategory.DELIVERY: (4, 16),
        VisitCategory.CAB: (2, 8),
        VisitCategory.GUEST: (40, 230),
        VisitCategory.SERVICE: (35, (duration or 60) - 5),
    }[category]
    overstays = rng.random() < (0.12 if category == VisitCategory.GUEST else 0.05)
    if overstays:
        stay = limit + timedelta(minutes=rng.randint(5, 95))
    else:
        stay = timedelta(minutes=rng.randint(*usual))
    exited_at = entered_at + stay
    if exited_at > b.now - timedelta(minutes=5):
        return  # still in progress at "now": the live simulator provides current visits

    guard_id = rng.choice(guard_ids)
    requested_at = entered_at - timedelta(seconds=rng.randint(70, 200))
    decided_at = requested_at + timedelta(seconds=rng.randint(20, 150))
    channel = rng.choices(
        [ApprovalChannel.WEB, ApprovalChannel.TELEGRAM, ApprovalChannel.GUARD], weights=[6, 3, 1]
    )[0]
    decider = guard_id if channel == ApprovalChannel.GUARD else rng.choice(flat.resident_ids)
    denied = rng.random() < 0.04

    visit = Visit(
        id=uuid.uuid4(),
        society_id=b.society_id,
        flat_id=flat.flat_id,
        visitor_id=person.visitor.id,
        plate_normalized=person.plate,
        category=category,
        purpose=person.purpose,
        status=VisitStatus.DENIED if denied else VisitStatus.EXITED,
        registered_by_id=guard_id,
        approved_by_id=None if denied else decider,
        duration_minutes=duration,
        created_at=requested_at,
        updated_at=decided_at if denied else exited_at,
    )
    b.db.add(visit)
    b.db.add(
        Approval(
            visit_id=visit.id,
            status=ApprovalStatus.DENIED if denied else ApprovalStatus.APPROVED,
            requested_at=requested_at,
            expires_at=requested_at + limits.approval_timeout,
            decided_at=decided_at,
            decided_by_id=decider,
            channel=channel,
            created_at=requested_at,
            updated_at=decided_at,
        )
    )
    changes: list[tuple[VisitStatus | None, VisitStatus, VisitTrigger | None, datetime]] = [
        (None, VisitStatus.PENDING_APPROVAL, None, requested_at)
    ]
    if denied:
        changes.append(
            (VisitStatus.PENDING_APPROVAL, VisitStatus.DENIED, VisitTrigger.DENY, decided_at)
        )
    else:
        b.summary.visits += 1
        visit.entered_at = entered_at
        visit.expected_exit_at = entered_at + limit
        visit.exited_at = exited_at
        changes += [
            (VisitStatus.PENDING_APPROVAL, VisitStatus.APPROVED, VisitTrigger.APPROVE, decided_at),
            (VisitStatus.APPROVED, VisitStatus.INSIDE, VisitTrigger.ENTER, entered_at),
        ]
        last = VisitStatus.INSIDE
        if overstays:
            changes.append(
                (last, VisitStatus.OVERSTAYED, VisitTrigger.OVERSTAY, entered_at + limit)
            )
            last = VisitStatus.OVERSTAYED
            if stay >= limit + timedelta(minutes=60):
                at = entered_at + limit + timedelta(minutes=60)
                changes.append((last, VisitStatus.ESCALATED, VisitTrigger.ESCALATE, at))
                last = VisitStatus.ESCALATED
        changes.append((last, VisitStatus.EXITED, VisitTrigger.EXIT, exited_at))
        if person.plate is not None:
            entry = b.event(
                lanes.entry,
                LaneDirection.ENTRY,
                person.plate,
                person.plate,
                entered_at,
                MatchResult.VISITOR,
                visit_id=visit.id,
            )
            leave = b.event(
                lanes.exit,
                LaneDirection.EXIT,
                person.plate,
                person.plate,
                exited_at,
                MatchResult.VISITOR,
                visit_id=visit.id,
            )
            b.links.append((visit, entry, leave))

    for from_status, to_status, trigger, at in changes:
        b.status_changes.append(
            VisitStatusChange(
                visit_id=visit.id,
                from_status=from_status,
                to_status=to_status,
                trigger=trigger,
                changed_at=at,
                actor_id=guard_id if trigger in (VisitTrigger.ENTER, None) else None,
            )
        )


def _resident_movements(
    b: _Builder,
    cars: list[ResidentCar],
    first_day: date,
    days: int,
    main_gate: GateLanes,
    service_gate: GateLanes,
) -> None:
    """Each car comes home on the first evening, then on most days leaves in the morning
    and returns at night. Entries and exits alternate, so reconciliation finds nothing."""
    rng = b.rng
    for car in cars:
        last_entry: GateEvent | None = None
        out_at = datetime.min.replace(tzinfo=IST)
        for offset in range(days + 1):
            day = first_day + timedelta(days=offset)
            lanes = main_gate if rng.random() < 0.85 else service_gate
            if last_entry is not None:
                goes_out = rng.random() < (0.45 if day.weekday() >= 5 else 0.7)
                if not goes_out:
                    continue
                out_at = b.at(day, RESIDENT_OUT_HOURS)
                if out_at <= last_entry.captured_at or out_at > b.now:
                    continue
                b.event(
                    lanes.exit,
                    LaneDirection.EXIT,
                    car.plate_raw,
                    car.plate,
                    out_at,
                    MatchResult.RESIDENT,
                    vehicle_id=car.vehicle_id,
                    paired_event_id=last_entry.id,
                )
                last_entry = None
            in_at = b.at(day, RESIDENT_IN_HOURS)
            if last_entry is None and offset > 0 and in_at <= out_at:
                in_at = out_at + timedelta(hours=rng.randint(3, 10))
            if in_at > b.now:
                break  # still out at "now"
            last_entry = b.event(
                lanes.entry,
                LaneDirection.ENTRY,
                car.plate_raw,
                car.plate,
                in_at,
                MatchResult.RESIDENT,
                vehicle_id=car.vehicle_id,
            )


def _current_state(
    b: _Builder,
    limits: VisitLimits,
    flats: list[FlatContacts],
    guard_ids: list[uuid.UUID],
    cars: list[ResidentCar],
    lanes: GateLanes,
    make_plate: PlateMaker,
    guests: list[_Person],
    focus_flat: FlatContacts | None,
) -> None:
    """A few things happening at the gate right now, so the guard console isn't empty
    when the demo opens: visitors inside (one long overdue, with a call task for the
    guard), a resident deciding, a request nobody answered, a watchlist alert, a plate the
    camera wasn't sure about, an unknown car, and residents coming and going.

    Every row matches what the real services would have written, including the ladder's
    emails (recorded as already sent), so the escalation job doesn't repeat any step."""
    rng, now = b.rng, b.now
    guard_id = guard_ids[0]
    people = iter(rng.sample(guests, k=6))

    def mins(n: float) -> datetime:
        return now - timedelta(minutes=n)

    def open_visit(
        person: _Person,
        category: VisitCategory,
        status: VisitStatus,
        *,
        requested: datetime,
        entered: datetime | None = None,
        plate: str | None = None,
        flat: FlatContacts | None = None,
    ) -> tuple[Visit, FlatContacts]:
        flat = flat or rng.choice(flats)
        visitor = Visitor(
            id=uuid.uuid4(), society_id=b.society_id, full_name=person.name, phone=person.phone
        )
        b.db.add(visitor)
        visit = Visit(
            id=uuid.uuid4(),
            society_id=b.society_id,
            flat_id=flat.flat_id,
            visitor_id=visitor.id,
            plate_normalized=plate,
            category=category,
            purpose=person.purpose,
            status=status,
            registered_by_id=guard_id,
            created_at=requested,
        )
        if entered is not None:
            visit.entered_at = entered
            visit.expected_exit_at = entered + limits.for_category(category)
        b.db.add(visit)
        b.status_changes.append(
            VisitStatusChange(
                visit_id=visit.id,
                from_status=None,
                to_status=VisitStatus.PENDING_APPROVAL,
                changed_at=requested,
                actor_id=guard_id,
            )
        )
        return visit, flat

    def approve(visit: Visit, flat: FlatContacts, requested: datetime, decided: datetime) -> None:
        decider = flat.resident_ids[0]
        visit.approved_by_id = decider
        b.db.add(
            Approval(
                visit_id=visit.id,
                status=ApprovalStatus.APPROVED,
                requested_at=requested,
                expires_at=requested + limits.approval_timeout,
                decided_at=decided,
                decided_by_id=decider,
                channel=ApprovalChannel.WEB,
            )
        )
        b.status_changes.append(
            VisitStatusChange(
                visit_id=visit.id,
                from_status=VisitStatus.PENDING_APPROVAL,
                to_status=VisitStatus.APPROVED,
                trigger=VisitTrigger.APPROVE,
                changed_at=decided,
            )
        )

    def enter(visit: Visit, at: datetime) -> None:
        b.status_changes.append(
            VisitStatusChange(
                visit_id=visit.id,
                from_status=VisitStatus.APPROVED,
                to_status=VisitStatus.INSIDE,
                trigger=VisitTrigger.ENTER,
                changed_at=at,
                actor_id=guard_id,
            )
        )
        if visit.plate_normalized:
            event = b.event(
                lanes.entry,
                LaneDirection.ENTRY,
                visit.plate_normalized,
                visit.plate_normalized,
                at,
                MatchResult.VISITOR,
                visit_id=visit.id,
            )
            b.links.append((visit, event, None))

    # Inside, plenty of time left; and a delivery close to its limit.
    for person, category, minutes_in, where in (
        (next(people), VisitCategory.GUEST, 50, focus_flat),
        (next(people), VisitCategory.DELIVERY, 14, None),
    ):
        plate = make_plate(two_wheeler=category == VisitCategory.DELIVERY)
        if category == VisitCategory.DELIVERY:
            person = _Person(person.name, person.phone, rng.choice(DELIVERY_RIDERS)[1], None)
        visit, flat = open_visit(
            person,
            category,
            VisitStatus.INSIDE,
            requested=mins(minutes_in + 2),
            entered=mins(minutes_in),
            plate=plate,
            flat=where,
        )
        approve(visit, flat, mins(minutes_in + 2), mins(minutes_in + 1))
        enter(visit, mins(minutes_in))
        b.summary.visits += 1

    # Long overdue: the ladder already emailed twice and opened a call task.
    plate = make_plate(two_wheeler=False)
    limit_minutes = limits.for_category(VisitCategory.GUEST).total_seconds() / 60
    entered = mins(limit_minutes + 75)
    visit, flat = open_visit(
        next(people),
        VisitCategory.GUEST,
        VisitStatus.ESCALATED,
        requested=entered - timedelta(minutes=2),
        entered=entered,
        plate=plate,
    )
    approve(visit, flat, entered - timedelta(minutes=2), entered - timedelta(minutes=1))
    enter(visit, entered)
    due = entered + limits.for_category(VisitCategory.GUEST)
    for from_status, to_status, trigger, at in (
        (VisitStatus.INSIDE, VisitStatus.OVERSTAYED, VisitTrigger.OVERSTAY, due),
        (
            VisitStatus.OVERSTAYED,
            VisitStatus.ESCALATED,
            VisitTrigger.ESCALATE,
            due + timedelta(minutes=60),
        ),
    ):
        b.status_changes.append(
            VisitStatusChange(
                visit_id=visit.id,
                from_status=from_status,
                to_status=to_status,
                trigger=trigger,
                changed_at=at,
            )
        )
    b.others.append(
        EscalationTask(
            visit_id=visit.id,
            status=EscalationTaskStatus.OPEN,
            created_at=due + timedelta(minutes=60),
        )
    )
    for step, at in (("overstay_notice", due), ("overstay_reminder", due + timedelta(minutes=30))):
        for user_id in flat.resident_ids:
            b.others.append(
                Notification(
                    society_id=b.society_id,
                    channel=NotificationChannel.EMAIL,
                    kind=step,
                    recipient="(demo history)",
                    user_id=user_id,
                    visit_id=visit.id,
                    status=NotificationStatus.SENT,
                    attempts=1,
                    sent_at=at,
                    created_at=at,
                    idempotency_key=f"visit:{visit.id}:{step}:resident:{user_id}",
                )
            )
    b.summary.visits += 1

    # At the gate: the camera read an unknown car, the guard registered the driver, and
    # the flat has a couple of minutes left to answer.
    plate = make_plate(two_wheeler=False)
    cab = next(people)
    visit, flat = open_visit(
        _Person(cab.name, cab.phone, rng.choice(CAB_DRIVERS)[1], None),
        VisitCategory.CAB,
        VisitStatus.PENDING_APPROVAL,
        requested=mins(0.7),
        plate=plate,
        flat=focus_flat,
    )
    b.event(
        lanes.entry,
        LaneDirection.ENTRY,
        plate,
        plate,
        mins(1.2),
        MatchResult.UNKNOWN,
        visit_id=visit.id,
    )
    b.db.add(
        Approval(
            visit_id=visit.id,
            status=ApprovalStatus.PENDING,
            requested_at=mins(0.7),
            expires_at=mins(0.7) + limits.approval_timeout,
        )
    )

    # Nobody at the flat answered: the guard decides.
    visit, flat = open_visit(
        next(people), VisitCategory.GUEST, VisitStatus.PENDING_APPROVAL, requested=mins(7)
    )
    b.db.add(
        Approval(
            visit_id=visit.id,
            status=ApprovalStatus.TIMED_OUT,
            requested_at=mins(7),
            expires_at=mins(7) + limits.approval_timeout,
            decided_at=mins(7) + limits.approval_timeout,
            channel=ApprovalChannel.GUARD,
        )
    )

    # Approved, walking in (no vehicle).
    visit, flat = open_visit(
        next(people), VisitCategory.GUEST, VisitStatus.APPROVED, requested=mins(4)
    )
    approve(visit, flat, mins(4), mins(3))

    # A watchlisted car came to the gate, the camera wasn't sure about one plate, and an
    # unknown car is waiting for the guard.
    watch = b.event(
        lanes.entry, LaneDirection.ENTRY, "HR26DK8337", "HR26DK8337", mins(9), MatchResult.WATCHLIST
    )
    b.others.append(
        Alert(
            society_id=b.society_id,
            kind=AlertKind.WATCHLIST,
            severity=AlertSeverity.HIGH,
            message=(
                "Watchlisted vehicle HR26DK8337 is entering: Reported for rash driving "
                "inside the society; entry needs admin approval"
            ),
            gate_event_id=watch.id,
            created_at=mins(9),
        )
    )
    unsure = make_plate(two_wheeler=False)
    review = b.event(
        lanes.entry,
        LaneDirection.ENTRY,
        unsure.replace("0", "O", 1),
        unsure,
        mins(5),
        MatchResult.LOW_CONFIDENCE,
    )
    review.confidence, review.needs_review, review.review_reason = (
        0.62,
        True,
        ReviewReason.LOW_CONFIDENCE,
    )
    review.ocr_fixes = 1 if "0" in unsure else 0
    stranger = make_plate(two_wheeler=True)
    b.event(lanes.entry, LaneDirection.ENTRY, stranger, stranger, mins(2), MatchResult.UNKNOWN)

    # Residents coming and going in the last half hour (the opposite of each car's last
    # read, so entries and exits keep alternating).
    for car in rng.sample(cars, k=6):
        last = b.last_read.get(car.plate)
        at = mins(rng.uniform(3, 30))
        if last is not None and last.captured_at >= at:
            continue
        if last is not None and last.direction == LaneDirection.ENTRY:
            b.event(
                lanes.exit,
                LaneDirection.EXIT,
                car.plate,
                car.plate,
                at,
                MatchResult.RESIDENT,
                vehicle_id=car.vehicle_id,
                paired_event_id=last.id,
            )
        else:
            b.event(
                lanes.entry,
                LaneDirection.ENTRY,
                car.plate,
                car.plate,
                at,
                MatchResult.RESIDENT,
                vehicle_id=car.vehicle_id,
            )
