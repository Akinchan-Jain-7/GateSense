"""Phase 2 "done when": a scripted morning at the gate produces the right visits, alerts and
review items. Each step is one camera read, sent through the real API in time order."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alert, GateEvent, PlateCorrection, Society, User, VisitStatusChange
from app.models.enums import LaneDirection, VisitCategory, VisitStatus, VisitTrigger
from tests import factories
from tests.factories import auth_headers

URL = "/api/v1/gate-events"


async def test_a_morning_at_the_gate(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society, guard: User
) -> None:
    # --- The society -------------------------------------------------------------------
    b402 = await factories.make_flat(db, society, "B", "402")
    c104 = await factories.make_flat(db, society, "C", "104")
    resident_car = await factories.make_vehicle(db, society, b402, "UP16AB1234")
    neighbour_car = await factories.make_vehicle(db, society, c104, "DL3CAS0042")
    await factories.make_watchlist_entry(db, society, "HR26DK8337", "Vendor contract ended")
    guest = await factories.make_visit(db, society, b402, "MH12DE1433")  # approved, arriving
    delivery = await factories.make_visit(
        db, society, c104, "UP14FT4410", category=VisitCategory.DELIVERY
    )
    gate = await factories.make_gate(db, society)
    _, entry_key = await factories.make_device(db, gate, LaneDirection.ENTRY)
    _, exit_key = await factories.make_device(db, gate, LaneDirection.EXIT)

    t0 = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=3)

    async def read(lane: str, plate: str, minute: float, confidence: float = 0.93) -> str:
        response = await client.post(
            URL,
            data={
                "plate_text": plate,
                "confidence": str(confidence),
                "captured_at": (t0 + timedelta(minutes=minute)).isoformat(),
            },
            headers={"X-Device-Key": entry_key if lane == "in" else exit_key},
        )
        assert response.status_code in (200, 201), response.text
        return str(response.json()["status"])

    # --- The script ----------------------------------------------------------------------
    steps = [
        ("out", "UP16AB1234", 0, 0.93),  # 07:00 resident leaves for work (no entry yet)
        ("in", "MH12DE1433", 10, 0.93),  # 07:10 the approved guest arrives
        ("in", "MH12DEI433", 10.05, 0.90),  # 3 s later, same car, OCR jitter -> debounced
        ("in", "UP14FT4410", 20, 0.93),  # 07:20 delivery arrives
        ("in", "HR26DK8337", 25, 0.93),  # 07:25 watchlisted vendor van at the gate
        ("in", "UP16AB1234", 40, 0.93),  # 07:40 resident comes back
        ("in", "DL3CAS0O42", 45, 0.55),  # 07:45 neighbour, but OCR is unsure -> review
        ("out", "UP14FT44I0", 50, 0.93),  # 07:50 delivery leaves (OCR: I for 1)
        ("in", "#@!", 55, 0.80),  # 07:55 mud on the plate -> unreadable -> review
        ("out", "UP16AB1234", 90, 0.93),  # 08:30 resident leaves again
        ("out", "MH12DE1433", 130, 0.93),  # 09:10 the guest leaves
    ]
    statuses = [await read(lane, plate, minute, conf) for lane, plate, minute, conf in steps]
    assert statuses.count("debounced") == 1
    assert statuses.count("created") == len(steps) - 1

    events = (await db.scalars(select(GateEvent).order_by(GateEvent.captured_at))).all()
    summary = [(e.direction.value, e.plate_normalized, e.match_result.value) for e in events]
    assert summary == [
        ("exit", "UP16AB1234", "resident"),
        ("entry", "MH12DE1433", "visitor"),
        ("entry", "UP14FT4410", "visitor"),
        ("entry", "HR26DK8337", "watchlist"),
        ("entry", "UP16AB1234", "resident"),
        ("entry", "DL3CAS0042", "low_confidence"),
        ("exit", "UP14FT4410", "visitor"),
        ("entry", None, "unknown"),
        ("exit", "UP16AB1234", "resident"),
        ("exit", "MH12DE1433", "visitor"),
    ]
    by_plate_and_lane = {(e.plate_normalized, e.direction, e.captured_at): e for e in events}

    # --- Resident pairing: the 07:00 exit had no entry; the 08:30 exit closes 07:40 --------
    first_exit, comeback, second_exit = (
        by_plate_and_lane[("UP16AB1234", LaneDirection.EXIT, t0)],
        by_plate_and_lane[("UP16AB1234", LaneDirection.ENTRY, t0 + timedelta(minutes=40))],
        by_plate_and_lane[("UP16AB1234", LaneDirection.EXIT, t0 + timedelta(minutes=90))],
    )
    assert first_exit.paired_event_id is None
    assert second_exit.paired_event_id == comeback.id
    assert comeback.vehicle_id == resident_car.id

    # --- Visits ---------------------------------------------------------------------------
    await db.refresh(guest)
    await db.refresh(delivery)
    assert guest.status is VisitStatus.EXITED
    assert guest.entered_at == t0 + timedelta(minutes=10)
    assert guest.expected_exit_at == t0 + timedelta(minutes=10, hours=4)
    assert guest.exited_at == t0 + timedelta(minutes=130)
    assert delivery.status is VisitStatus.EXITED
    assert delivery.expected_exit_at == t0 + timedelta(minutes=40)  # 20-minute limit

    history = (
        await db.scalars(
            select(VisitStatusChange)
            .where(VisitStatusChange.visit_id == guest.id)
            .order_by(VisitStatusChange.changed_at)
        )
    ).all()
    assert [(h.from_status, h.to_status, h.trigger) for h in history] == [
        (VisitStatus.APPROVED, VisitStatus.INSIDE, VisitTrigger.ENTER),
        (VisitStatus.INSIDE, VisitStatus.EXITED, VisitTrigger.EXIT),
    ]
    assert all(h.gate_event_id is not None for h in history)

    # --- Alerts ---------------------------------------------------------------------------
    alerts = (await db.scalars(select(Alert))).all()
    assert [a.message for a in alerts] == [
        "Watchlisted vehicle HR26DK8337 is entering: Vendor contract ended"
    ]

    # --- Review queue: the unsure neighbour and the muddy plate, newest first --------------
    headers = auth_headers(guard)
    queue = (await client.get(f"{URL}/review-queue", headers=headers)).json()
    assert [(i["plate_raw"], i["review_reason"]) for i in queue["items"]] == [
        ("#@!", "unreadable"),
        ("DL3CAS0O42", "low_confidence"),
    ]

    # The guard confirms the neighbour and dismisses the mud.
    unsure_id, mud_id = queue["items"][1]["id"], queue["items"][0]["id"]
    confirmed = await client.post(
        f"{URL}/{unsure_id}/review",
        json={"action": "correct", "plate": "DL 3C AS 0042"},
        headers=headers,
    )
    assert confirmed.json()["match_result"] == "resident"
    assert confirmed.json()["vehicle_id"] == str(neighbour_car.id)
    await client.post(f"{URL}/{mud_id}/review", json={"action": "dismiss"}, headers=headers)

    assert (await client.get(f"{URL}/review-queue", headers=headers)).json()["total"] == 0
    corrections = (await db.scalars(select(PlateCorrection))).all()
    assert [(c.gate_event_id, c.original_plate, c.corrected_plate) for c in corrections] == [
        (uuid.UUID(unsure_id), "DL3CAS0O42", "DL3CAS0042")
    ]
