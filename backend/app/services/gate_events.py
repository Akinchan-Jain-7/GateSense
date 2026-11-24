"""The gate-event engine: what happens when a camera reports a plate.

    ingest_read()
      1. Idempotency: same device + plate text + capture time already stored? -> "duplicate"
      2. Repair the OCR text into a valid plate (plates.read_ocr_plate)
      3. Debounce: same plate on the same lane moments ago? -> "debounced"
      4. Save the snapshot, store the event
      5. Decide what it is (apply_match):
           watchlist hit      -> high-priority alert (checked even for unsure reads)
           unreadable/unsure  -> guard review queue, nothing automatic
           resident vehicle   -> logged; an EXIT closes the vehicle's open ENTRY
           expected visitor   -> visit moves APPROVED -> INSIDE, or INSIDE -> EXITED
           guest pass (entry) -> a new approved visit, admitted at once, one use counted
           anything else      -> UNKNOWN (the guard registers the visitor, Phase 4)

A guard's correction of a review item (`review_event`) runs step 5 again with the
corrected plate, so both paths share exactly the same rules.
"""

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from redis.asyncio import Redis
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, aliased

from app.core.config import Settings
from app.models import (
    Alert,
    Device,
    GateEvent,
    GuestPass,
    PlateCorrection,
    User,
    Vehicle,
    Visit,
    WatchlistEntry,
)
from app.models.enums import (
    AlertKind,
    AlertSeverity,
    LaneDirection,
    MatchResult,
    ReviewReason,
    VisitStatus,
    VisitTrigger,
)
from app.services import debounce, guest_passes, realtime, society_settings
from app.services.db_helpers import get_in_society
from app.services.errors import ConflictError, InvalidInputError
from app.services.pagination import PageRequest, PageResult, paginate
from app.services.plates import (
    PlateReading,
    clean_plate,
    closest_plates,
    normalize_typed_plate,
    read_ocr_plate,
    typed_reading,
)
from app.services.storage import SnapshotStorage, detect_image_type
from app.services.visit_state import INSIDE_STATUSES
from app.services.visits import transition_visit

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlateRead:
    """One read as a camera reports it."""

    plate_text: str
    confidence: float
    captured_at: datetime
    snapshot: bytes | None = None


@dataclass(frozen=True)
class IngestResult:
    status: Literal["created", "duplicate", "debounced"]
    # The stored event: the new one, the earlier copy, or the one this read was folded into
    # (None only if a debounced read points at an event that was never saved).
    event: GateEvent | None


def event_hash(device_id: uuid.UUID, plate_text: str, captured_at: datetime) -> str:
    """Fingerprint of a read. A retry of the same upload has the same fingerprint."""
    moment = captured_at.astimezone(UTC).isoformat(timespec="milliseconds")
    return hashlib.sha256(f"{device_id}|{clean_plate(plate_text)}|{moment}".encode()).hexdigest()


def snapshot_key(event: GateEvent, extension: str) -> str:
    return f"{event.society_id}/{event.captured_at:%Y/%m/%d}/{event.id}.{extension}"


def _check_capture_time(settings: Settings, captured_at: datetime, now: datetime) -> datetime:
    if captured_at.tzinfo is None:
        raise InvalidInputError("captured_at must include a timezone, e.g. 2026-11-21T09:30:00Z")
    skew = timedelta(seconds=settings.gate_event_max_clock_skew_seconds)
    if captured_at > now + skew:
        raise InvalidInputError("captured_at is in the future; check the camera's clock")
    return captured_at.astimezone(UTC)


async def ingest_read(
    db: AsyncSession,
    redis: Redis,
    storage: SnapshotStorage,
    settings: Settings,
    device: Device,
    read: PlateRead,
    *,
    now: datetime | None = None,
) -> IngestResult:
    now = now or datetime.now(UTC)
    captured_at = _check_capture_time(settings, read.captured_at, now)
    image_type = detect_image_type(read.snapshot) if read.snapshot is not None else None
    fingerprint = event_hash(device.id, read.plate_text, captured_at)

    # 1. Idempotency: an exact retry gets the original event back.
    existing = await db.scalar(select(GateEvent).where(GateEvent.event_hash == fingerprint))
    if existing is not None:
        return IngestResult(status="duplicate", event=existing)

    # 2. Repair the plate text.
    reading = read_ocr_plate(read.plate_text)
    plate_key = reading.plate if reading else clean_plate(read.plate_text)

    # 3. Debounce (skipped for empty text: there's nothing to compare).
    event_id = uuid.uuid4()
    if plate_key:
        folded_into = await debounce.check_and_mark(
            redis,
            device_id=device.id,
            plate=plate_key,
            captured_at=captured_at,
            new_event_id=event_id,
            cooldown_seconds=settings.gate_event_cooldown_seconds,
        )
        if folded_into is not None:
            return IngestResult(status="debounced", event=await db.get(GateEvent, folded_into))

    # 4. Store the event (and its snapshot), then 5. decide what it is. If anything fails
    #    here the event isn't saved, so the debounce mark from step 3 is released: the
    #    camera retries, and the retry must count as a new read, not as "seen just now".
    try:
        event = GateEvent(
            id=event_id,
            society_id=device.gate.society_id,
            gate_id=device.gate_id,
            device_id=device.id,
            direction=device.direction,
            plate_raw=read.plate_text[:32],
            # Set now so the INSERT carries them (apply_match sets the same values).
            plate_normalized=reading.plate if reading else None,
            ocr_fixes=reading.fixes if reading else 0,
            confidence=read.confidence,
            captured_at=captured_at,
            event_hash=fingerprint,
            match_result=MatchResult.UNKNOWN,
            needs_review=False,
        )
        if read.snapshot is not None and image_type is not None:
            content_type, extension = image_type
            event.snapshot_path = snapshot_key(event, extension)
            await storage.save(event.snapshot_path, read.snapshot, content_type)
        try:
            # INSERT inside a savepoint: the unique event_hash catches a copy of this read
            # arriving at the same moment, and only the savepoint is rolled back.
            async with db.begin_nested():
                db.add(event)
        except IntegrityError:
            # The same read arrived twice at the same moment and the other request won.
            if event.snapshot_path:
                await storage.delete(event.snapshot_path)
            winner = await db.scalar(select(GateEvent).where(GateEvent.event_hash == fingerprint))
            if winner is None:
                raise
            return IngestResult(status="duplicate", event=winner)

        await apply_match(db, settings, event, reading, trusted=False)
        await db.commit()
    except BaseException:
        if plate_key:
            await debounce.release(redis, device_id=device.id, plate=plate_key, event_id=event_id)
        raise
    await _publish(db, redis, event)
    logger.info(
        "gate event",
        extra={
            "event_id": str(event.id),
            "device_id": str(device.id),
            "direction": event.direction.value,
            "match": event.match_result.value,
            "needs_review": event.needs_review,
        },
    )
    return IngestResult(status="created", event=event)


async def _publish(db: AsyncSession, redis: Redis, event: GateEvent) -> None:
    """Tell the guard console (and, for visits, the flat's residents) what just happened."""
    from app.schemas.gate_event import AlertRead, GateEventRead
    from app.services import visitors

    console = [realtime.console_channel(event.society_id)]
    read = GateEventRead.model_validate(event)
    await realtime.publish(redis, console, "gate_event.created", read)
    if event.match_result is MatchResult.WATCHLIST:  # the only reads that raise an alert
        for alert in await db.scalars(select(Alert).where(Alert.gate_event_id == event.id)):
            await realtime.publish(redis, console, "alert.created", AlertRead.model_validate(alert))
    if event.visit_id is not None:
        visit = await visitors.load_visit(db, event.visit_id)
        await visitors.publish_visit(redis, db, visit, "visit.updated")


# --- Matching ------------------------------------------------------------------------


async def apply_match(
    db: AsyncSession,
    settings: Settings,
    event: GateEvent,
    reading: PlateReading | None,
    *,
    trusted: bool,
    actor_id: uuid.UUID | None = None,
) -> None:
    """Fill in what the event is and trigger its side effects. The caller commits.

    `trusted` = the plate was typed or confirmed by a guard, so confidence doesn't matter.
    """
    if reading is None:
        event.plate_normalized = None
        event.match_result = MatchResult.UNKNOWN
        _send_to_review(event, ReviewReason.UNREADABLE)
        return
    event.plate_normalized = reading.plate
    event.ocr_fixes = reading.fixes
    limits = await society_settings.visit_limits(db, settings, event.society_id)
    unsure = not trusted and event.confidence < limits.plate_confidence_threshold

    # Watchlist first, even for unsure reads: a false alarm is cheap, a missed one isn't.
    flagged = await _watchlist_hit(db, settings, event.society_id, reading.plate)
    if flagged is not None:
        entry, distance = flagged
        event.match_result = MatchResult.WATCHLIST
        event.match_distance = distance
        db.add(_watchlist_alert(event, entry, distance))
        if unsure:
            _send_to_review(event, ReviewReason.LOW_CONFIDENCE)
        return

    if unsure:
        # Don't open gates or close visits on a guess; a guard confirms it first.
        event.match_result = MatchResult.LOW_CONFIDENCE
        _send_to_review(event, ReviewReason.LOW_CONFIDENCE)
        return

    known = await _known_plates(db, settings, event)
    closest = closest_plates(reading.plate, known.keys(), settings.plate_fuzzy_max_distance)
    if closest is None:
        event.match_result = MatchResult.UNKNOWN
        return
    plate = closest.unique
    if plate is None:
        event.match_result = MatchResult.UNKNOWN
        _send_to_review(event, ReviewReason.AMBIGUOUS_MATCH)
        return

    event.match_distance = closest.distance
    kind, match_id = known[plate]
    if kind is Vehicle:
        event.match_result = MatchResult.RESIDENT
        event.vehicle_id = match_id
        if event.direction is LaneDirection.EXIT:
            await _close_resident_entry(db, event, match_id)
    elif kind is GuestPass:
        guest_pass = await db.get_one(GuestPass, match_id)
        event.match_result = MatchResult.GUEST_PASS
        visit = await guest_passes.admit_with_pass(
            db,
            settings,
            guest_pass,
            at=event.captured_at,
            plate=event.plate_normalized,
            gate_event_id=event.id,
            actor_id=actor_id,
        )
        event.visit_id = visit.id
    else:
        match = await db.get_one(Visit, match_id)
        event.match_result = MatchResult.VISITOR
        event.visit_id = match.id
        trigger = (
            VisitTrigger.ENTER if event.direction is LaneDirection.ENTRY else VisitTrigger.EXIT
        )
        await transition_visit(
            db,
            settings,
            match,
            trigger,
            at=event.captured_at,
            actor_id=actor_id,
            gate_event_id=event.id,
            note=f"{event.direction.value} camera read" if actor_id is None else "guard review",
        )


def _send_to_review(event: GateEvent, reason: ReviewReason) -> None:
    event.needs_review = True
    event.review_reason = reason


async def _watchlist_hit(
    db: AsyncSession, settings: Settings, society_id: uuid.UUID, plate: str
) -> tuple[WatchlistEntry, int] | None:
    max_distance = settings.plate_fuzzy_max_distance
    entries = {
        entry.plate_normalized: entry
        for entry in await db.scalars(
            select(WatchlistEntry).where(
                WatchlistEntry.society_id == society_id,
                WatchlistEntry.is_active.is_(True),
                _length_near(WatchlistEntry.plate_normalized, plate, max_distance),
            )
        )
    }
    closest = closest_plates(plate, entries, max_distance)
    if closest is None:
        return None
    # Two flagged plates equally close: alert on the first; the guard sees the plate anyway.
    return entries[closest.plates[0]], closest.distance


def _watchlist_alert(event: GateEvent, entry: WatchlistEntry, distance: int) -> Alert:
    lane = "entering" if event.direction is LaneDirection.ENTRY else "leaving"
    if distance == 0:
        message = f"Watchlisted vehicle {entry.plate_normalized} is {lane}: {entry.reason}"
    else:
        message = (
            f"Possible watchlist match: read {event.plate_normalized}, flagged plate "
            f"{entry.plate_normalized} is {lane}: {entry.reason}"
        )
    return Alert(
        society_id=event.society_id,
        kind=AlertKind.WATCHLIST,
        severity=AlertSeverity.HIGH,
        message=message,
        gate_event_id=event.id,
    )


def _length_near(
    column: InstrumentedAttribute[str] | InstrumentedAttribute[str | None],
    plate: str,
    max_distance: int,
) -> ColumnElement[bool]:
    """SQL filter: only plates whose length could be within max_distance edits of `plate`."""
    return func.length(column).between(len(plate) - max_distance, len(plate) + max_distance)


type Candidate = tuple[type[Vehicle] | type[Visit] | type[GuestPass], uuid.UUID]


async def _known_plates(
    db: AsyncSession, settings: Settings, event: GateEvent
) -> dict[str, Candidate]:
    """Plates this read could belong to: resident vehicles, visits expecting this lane, and
    (at the entry lane) guest passes valid at the capture time.

    At the entry lane, approved visits waiting to arrive; at the exit lane, visits whose
    vehicle is inside. A resident vehicle wins if a visit has the same plate.

    Only (plate, id) pairs are fetched, not whole rows: every read compares against every
    plausible plate in the society, and building hundreds of ORM objects per read was the
    biggest CPU cost in the Phase 7 load test. The one winner is loaded afterwards.
    """
    plate = event.plate_normalized or ""
    max_distance = settings.plate_fuzzy_max_distance
    wanted = (
        {VisitStatus.APPROVED} if event.direction is LaneDirection.ENTRY else set(INSIDE_STATUSES)
    )
    visits = await db.execute(
        select(Visit.plate_normalized, Visit.id)
        .where(
            Visit.society_id == event.society_id,
            Visit.status.in_(wanted),
            Visit.plate_normalized.is_not(None),
            _length_near(Visit.plate_normalized, plate, max_distance),
        )
        # Oldest first, so the newest visit for a plate overwrites older ones below.
        .order_by(Visit.created_at)
    )
    vehicles = await db.execute(
        select(Vehicle.plate_normalized, Vehicle.id).where(
            Vehicle.society_id == event.society_id,
            Vehicle.is_active.is_(True),
            _length_near(Vehicle.plate_normalized, plate, max_distance),
        )
    )
    known: dict[str, Candidate] = {}
    if event.direction is LaneDirection.ENTRY:
        # Lowest priority first: a guest pass, then an expected visit, then a resident's car.
        for guest_pass in await guest_passes.plate_passes(
            db, event.society_id, plate, event.captured_at, max_distance
        ):
            if guest_pass.plate_normalized:
                known[guest_pass.plate_normalized] = (GuestPass, guest_pass.id)
    for visit_plate, visit_id in visits:
        if visit_plate:
            known[visit_plate] = (Visit, visit_id)
    for vehicle_plate, vehicle_id in vehicles:
        known[vehicle_plate] = (Vehicle, vehicle_id)
    return known


async def _close_resident_entry(
    db: AsyncSession, exit_event: GateEvent, vehicle_id: uuid.UUID
) -> None:
    """Pair an EXIT with the vehicle's latest ENTRY, if that entry is still open.

    If the latest entry was already closed (or there is none), the exit stays unpaired:
    that's an "exit without entry" for the nightly reconciliation to report.

    The entry row is locked (`FOR UPDATE`) before checking whether it's closed. Two exits
    of the same car arriving together (two exit cameras) would otherwise both see it open
    and both pair with it; with the lock, the second waits for the first to commit, then
    sees it closed. (Found by the Phase 7 load test, see docs/performance.md.)
    """
    latest_entry = await db.scalar(
        select(GateEvent)
        .where(
            GateEvent.vehicle_id == vehicle_id,
            GateEvent.direction == LaneDirection.ENTRY,
            GateEvent.captured_at <= exit_event.captured_at,
            GateEvent.id != exit_event.id,
        )
        .order_by(GateEvent.captured_at.desc())
        .limit(1)
        .with_for_update()
    )
    if latest_entry is None:
        return
    closer = aliased(GateEvent)
    already_closed = await db.scalar(
        select(func.count()).select_from(closer).where(closer.paired_event_id == latest_entry.id)
    )
    if not already_closed:
        exit_event.paired_event_id = latest_entry.id


# --- Guard review queue ----------------------------------------------------------------


async def review_event(
    db: AsyncSession,
    settings: Settings,
    actor: User,
    event_id: uuid.UUID,
    corrected_plate: str | None,
) -> GateEvent:
    """Resolve a review item: confirm/correct the plate (re-runs matching), or dismiss it.

    Every confirmed plate is saved in `plate_corrections` next to what OCR read: that pair
    is labelled training data for the OCR model (Phase 3).
    """
    event = await get_event(db, actor, event_id)
    if not event.needs_review:
        raise ConflictError("This event isn't in the review queue")
    if event.reviewed_at is not None:
        raise ConflictError("This event was already reviewed")

    event.reviewed_at = datetime.now(UTC)
    event.reviewed_by_id = actor.id
    if corrected_plate is not None:
        plate = normalize_typed_plate(corrected_plate)
        db.add(
            PlateCorrection(
                gate_event_id=event.id,
                original_plate=event.plate_raw,
                corrected_plate=plate,
                corrected_by_id=actor.id,
            )
        )
        if event.match_result is not MatchResult.WATCHLIST or plate != event.plate_normalized:
            _reset_match(event)
            reading = typed_reading(plate)
            await apply_match(db, settings, event, reading, trusted=True, actor_id=actor.id)
            event.ocr_fixes = None  # the plate now comes from a person, not from OCR
    await db.commit()
    return event


def _reset_match(event: GateEvent) -> None:
    event.match_result = MatchResult.UNKNOWN
    event.match_distance = None
    event.vehicle_id = None
    event.visit_id = None
    # needs_review stays True: the event *was* reviewed, which the history should show.


# --- Reading events ----------------------------------------------------------------------


async def get_event(db: AsyncSession, actor: User, event_id: uuid.UUID) -> GateEvent:
    return await get_in_society(db, GateEvent, event_id, actor.society_id)


async def list_events(
    db: AsyncSession,
    actor: User,
    page: PageRequest,
    *,
    direction: LaneDirection | None = None,
    match_result: MatchResult | None = None,
    needs_review: bool | None = None,
    gate_id: uuid.UUID | None = None,
    q: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> PageResult[GateEvent]:
    statement = (
        select(GateEvent)
        .where(GateEvent.society_id == actor.society_id)
        .order_by(GateEvent.captured_at.desc())
    )
    if direction:
        statement = statement.where(GateEvent.direction == direction)
    if match_result:
        statement = statement.where(GateEvent.match_result == match_result)
    if needs_review is not None:
        statement = statement.where(GateEvent.needs_review.is_(needs_review))
    if gate_id:
        statement = statement.where(GateEvent.gate_id == gate_id)
    if q:
        statement = statement.where(GateEvent.plate_normalized.contains(clean_plate(q)))
    if since:
        statement = statement.where(GateEvent.captured_at >= since)
    if until:
        statement = statement.where(GateEvent.captured_at < until)
    return await paginate(db, statement, page)


async def review_queue(db: AsyncSession, actor: User, page: PageRequest) -> PageResult[GateEvent]:
    """Unresolved review items, newest first (the car at the gate right now is on top)."""
    statement = (
        select(GateEvent)
        .where(
            GateEvent.society_id == actor.society_id,
            GateEvent.needs_review.is_(True),
            GateEvent.reviewed_at.is_(None),
        )
        .order_by(GateEvent.captured_at.desc())
    )
    return await paginate(db, statement, page)
