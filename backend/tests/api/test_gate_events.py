"""The gate-event engine through the API, on real Postgres and Redis."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx2
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_snapshot_storage
from app.main import app
from app.models import (
    Alert,
    Device,
    Flat,
    Gate,
    GateEvent,
    PlateCorrection,
    Society,
    User,
    Visit,
)
from app.models.enums import LaneDirection, MatchResult, UserRole, VisitStatus
from app.services.storage import LocalSnapshotStorage
from tests import factories
from tests.factories import auth_headers

URL = "/api/v1/gate-events"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def ago(minutes: float = 0) -> datetime:
    return datetime.now(UTC) - timedelta(minutes=minutes)


async def post_read(
    client: httpx2.AsyncClient,
    key: str,
    plate: str,
    *,
    confidence: float = 0.95,
    at: datetime | None = None,
    snapshot: bytes | None = None,
    direction: str | None = None,
) -> httpx2.Response:
    data: dict[str, str] = {
        "plate_text": plate,
        "confidence": str(confidence),
        "captured_at": (at or ago(10)).isoformat(),
    }
    if direction:
        data["direction"] = direction
    files = {"snapshot": ("car.jpg", snapshot, "image/jpeg")} if snapshot is not None else None
    return await client.post(URL, data=data, files=files, headers={"X-Device-Key": key})


@pytest.fixture
async def entry_key(db: AsyncSession, society: Society) -> str:
    gate = await factories.make_gate(db, society)
    _, key = await factories.make_device(db, gate, LaneDirection.ENTRY)
    return key


@pytest.fixture
async def exit_key(db: AsyncSession, society: Society) -> str:
    gate = await factories.make_gate(db, society, "Back Gate")
    _, key = await factories.make_device(db, gate, LaneDirection.EXIT)
    return key


async def count_events(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(GateEvent)) or 0


# --- Device authentication and input checks -------------------------------------------


async def test_cameras_need_a_valid_device_key(client: httpx2.AsyncClient) -> None:
    missing = await client.post(URL, data={"plate_text": "DL01AB1234", "confidence": "0.9"})
    assert missing.status_code == 401
    wrong = await post_read(client, "gsd_not-a-real-key", "DL01AB1234")
    assert wrong.status_code == 401


async def test_user_tokens_cant_post_events(client: httpx2.AsyncClient, guard: User) -> None:
    response = await client.post(
        URL, data={"plate_text": "DL01AB1234", "confidence": "0.9"}, headers=auth_headers(guard)
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("field", "value"),
    [("confidence", "1.5"), ("confidence", "-0.1"), ("plate_text", ""), ("plate_text", "X" * 33)],
)
async def test_bad_form_values_are_rejected(
    client: httpx2.AsyncClient, entry_key: str, field: str, value: str
) -> None:
    data = {"plate_text": "DL01AB1234", "confidence": "0.9", field: value}
    response = await client.post(URL, data=data, headers={"X-Device-Key": entry_key})
    assert response.status_code == 422


async def test_capture_time_in_the_future_is_rejected(
    client: httpx2.AsyncClient, entry_key: str
) -> None:
    response = await post_read(client, entry_key, "DL01AB1234", at=ago(-60))
    assert response.status_code == 422
    assert "future" in response.json()["detail"]


async def test_capture_time_needs_a_timezone(client: httpx2.AsyncClient, entry_key: str) -> None:
    data = {"plate_text": "DL01AB1234", "confidence": "0.9", "captured_at": "2026-11-21T09:00:00"}
    response = await client.post(URL, data=data, headers={"X-Device-Key": entry_key})
    assert response.status_code == 422
    assert "timezone" in response.json()["detail"]


async def test_capture_time_defaults_to_now(client: httpx2.AsyncClient, entry_key: str) -> None:
    data = {"plate_text": "DL01AB1234", "confidence": "0.9"}
    response = await client.post(URL, data=data, headers={"X-Device-Key": entry_key})
    assert response.status_code == 201
    captured = datetime.fromisoformat(response.json()["event"]["captured_at"])
    assert abs((datetime.now(UTC) - captured).total_seconds()) < 60


async def test_direction_must_match_the_device_lane(
    client: httpx2.AsyncClient, entry_key: str
) -> None:
    response = await post_read(client, entry_key, "DL01AB1234", direction="exit")
    assert response.status_code == 422
    assert "entry lane" in response.json()["detail"]
    ok = await post_read(client, entry_key, "DL01AB1234", direction="entry")
    assert ok.status_code == 201


# --- Idempotency and debounce -----------------------------------------------------------


async def test_retrying_the_same_read_returns_the_original_event(
    client: httpx2.AsyncClient, db: AsyncSession, entry_key: str
) -> None:
    at = ago(5)
    first = await post_read(client, entry_key, "DL01AB1234", at=at)
    retry = await post_read(client, entry_key, "DL01AB1234", at=at)

    assert first.status_code == 201
    assert retry.status_code == 200
    assert retry.json()["status"] == "duplicate"
    assert retry.json()["event"]["id"] == first.json()["event"]["id"]
    assert await count_events(db) == 1


async def test_same_plate_moments_later_is_debounced(
    client: httpx2.AsyncClient, db: AsyncSession, entry_key: str
) -> None:
    first = await post_read(client, entry_key, "DL01AB1234", at=ago(5))
    # A slightly different OCR string for the same plate still counts as the same car.
    again = await post_read(client, entry_key, "DLO1AB1234", at=ago(5) + timedelta(seconds=4))

    assert again.status_code == 200
    assert again.json()["status"] == "debounced"
    assert again.json()["event"]["id"] == first.json()["event"]["id"]
    assert await count_events(db) == 1

    later = await post_read(client, entry_key, "DL01AB1234", at=ago(5) + timedelta(seconds=40))
    assert later.status_code == 201
    assert await count_events(db) == 2


# --- Matching --------------------------------------------------------------------------


async def test_resident_vehicle_is_matched_exactly(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society, flat: Flat, entry_key: str
) -> None:
    vehicle = await factories.make_vehicle(db, society, flat, "UP16AB1234")
    response = await post_read(client, entry_key, "up16 ab 1234")

    event = response.json()["event"]
    assert response.status_code == 201
    assert event["match_result"] == "resident"
    assert event["vehicle_id"] == str(vehicle.id)
    assert (event["plate_normalized"], event["match_distance"], event["ocr_fixes"]) == (
        "UP16AB1234",
        0,
        0,
    )
    assert event["needs_review"] is False


async def test_ocr_look_alikes_are_fixed_before_matching(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society, flat: Flat, entry_key: str
) -> None:
    await factories.make_vehicle(db, society, flat, "UP16AB1234")
    event = (await post_read(client, entry_key, "UP16ABI234")).json()["event"]
    assert (event["match_result"], event["plate_normalized"], event["ocr_fixes"]) == (
        "resident",
        "UP16AB1234",
        1,
    )


async def test_one_character_off_still_matches(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society, flat: Flat, entry_key: str
) -> None:
    vehicle = await factories.make_vehicle(db, society, flat, "UP16AB1234")
    event = (await post_read(client, entry_key, "UP16AB1284")).json()["event"]
    assert (event["match_result"], event["vehicle_id"], event["match_distance"]) == (
        "resident",
        str(vehicle.id),
        1,
    )


async def test_equally_close_to_two_plates_goes_to_review(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society, flat: Flat, entry_key: str
) -> None:
    await factories.make_vehicle(db, society, flat, "UP16AB1234")
    await factories.make_vehicle(db, society, flat, "UP16AB1236")
    event = (await post_read(client, entry_key, "UP16AB1235")).json()["event"]
    assert (event["match_result"], event["needs_review"], event["review_reason"]) == (
        "unknown",
        True,
        "ambiguous_match",
    )
    assert event["vehicle_id"] is None


async def test_inactive_vehicles_and_other_societies_dont_match(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society, flat: Flat, entry_key: str
) -> None:
    sold = await factories.make_vehicle(db, society, flat, "UP16AB1234")
    sold.is_active = False
    other = await factories.make_society(db, "Other Society")
    other_flat = await factories.make_flat(db, other, "A", "101")
    await factories.make_vehicle(db, other, other_flat, "HR26DK8337")
    await db.commit()

    for plate in ("UP16AB1234", "HR26DK8337"):
        event = (await post_read(client, entry_key, plate)).json()["event"]
        assert event["match_result"] == "unknown"
        assert event["needs_review"] is False


async def test_low_confidence_read_waits_for_a_guard(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society, flat: Flat, entry_key: str
) -> None:
    await factories.make_vehicle(db, society, flat, "UP16AB1234")
    event = (await post_read(client, entry_key, "UP16AB1234", confidence=0.42)).json()["event"]
    assert (event["match_result"], event["needs_review"], event["review_reason"]) == (
        "low_confidence",
        True,
        "low_confidence",
    )
    assert event["vehicle_id"] is None  # nothing automatic on a guess


async def test_unreadable_text_goes_to_review(client: httpx2.AsyncClient, entry_key: str) -> None:
    event = (await post_read(client, entry_key, "#?!--")).json()["event"]
    assert event["plate_normalized"] is None
    assert (event["match_result"], event["review_reason"]) == ("unknown", "unreadable")


async def test_watchlisted_plate_raises_a_high_alert(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society, entry_key: str
) -> None:
    await factories.make_watchlist_entry(db, society, "HR26DK8337", "Rash driving")
    event = (await post_read(client, entry_key, "HR26DKB337")).json()["event"]

    assert (event["match_result"], event["match_distance"]) == ("watchlist", 0)
    alert = await db.scalar(select(Alert).where(Alert.gate_event_id == uuid.UUID(event["id"])))
    assert alert is not None
    assert alert.severity == "high"
    assert alert.message == "Watchlisted vehicle HR26DK8337 is entering: Rash driving"


async def test_near_watchlist_match_says_possible(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society, exit_key: str
) -> None:
    await factories.make_watchlist_entry(db, society, "HR26DK8337", "Rash driving")
    event = (await post_read(client, exit_key, "HR26DK8331")).json()["event"]
    assert (event["match_result"], event["match_distance"]) == ("watchlist", 1)
    alert = await db.scalar(select(Alert).where(Alert.gate_event_id == uuid.UUID(event["id"])))
    assert alert is not None
    assert alert.message.startswith("Possible watchlist match: read HR26DK8331")
    assert "is leaving" in alert.message


async def test_watchlist_is_checked_even_for_unsure_reads(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society, entry_key: str
) -> None:
    await factories.make_watchlist_entry(db, society, "HR26DK8337")
    event = (await post_read(client, entry_key, "HR26DK8337", confidence=0.3)).json()["event"]
    assert (event["match_result"], event["needs_review"]) == ("watchlist", True)
    assert await db.scalar(select(func.count()).select_from(Alert)) == 1


async def test_watchlist_beats_a_resident_match(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society, flat: Flat, entry_key: str
) -> None:
    await factories.make_vehicle(db, society, flat, "UP16AB1234")
    await factories.make_watchlist_entry(db, society, "UP16AB1234")
    event = (await post_read(client, entry_key, "UP16AB1234")).json()["event"]
    assert event["match_result"] == "watchlist"


# --- Resident entry/exit pairing --------------------------------------------------------


async def test_resident_exit_closes_the_latest_open_entry(
    client: httpx2.AsyncClient,
    db: AsyncSession,
    society: Society,
    flat: Flat,
    entry_key: str,
    exit_key: str,
) -> None:
    await factories.make_vehicle(db, society, flat, "UP16AB1234")
    entry = (await post_read(client, entry_key, "UP16AB1234", at=ago(120))).json()["event"]
    exit_ = (await post_read(client, exit_key, "UP16AB1234", at=ago(60))).json()["event"]
    assert exit_["paired_event_id"] == entry["id"]

    # Leaving again without a recorded entry: nothing to close (reconciliation flags it).
    again = (await post_read(client, exit_key, "UP16AB1234", at=ago(30))).json()["event"]
    assert again["match_result"] == "resident"
    assert again["paired_event_id"] is None


async def test_exit_without_any_entry_is_unpaired(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society, flat: Flat, exit_key: str
) -> None:
    await factories.make_vehicle(db, society, flat, "UP16AB1234")
    event = (await post_read(client, exit_key, "UP16AB1234")).json()["event"]
    assert (event["match_result"], event["paired_event_id"]) == ("resident", None)


# --- Visitors ---------------------------------------------------------------------------


async def test_approved_visitor_entering_starts_the_visit_clock(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society, flat: Flat, entry_key: str
) -> None:
    visit = await factories.make_visit(db, society, flat, "DL8CAF5030")
    at = ago(15)
    event = (await post_read(client, entry_key, "DL8CAF5O30", at=at)).json()["event"]

    assert (event["match_result"], event["visit_id"]) == ("visitor", str(visit.id))
    await db.refresh(visit)
    assert visit.status is VisitStatus.INSIDE
    assert visit.entered_at == at
    assert visit.expected_exit_at == at + timedelta(hours=4)  # guest default
    assert str(visit.entry_event_id) == event["id"]


async def test_visit_waiting_for_approval_is_not_admitted(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society, flat: Flat, entry_key: str
) -> None:
    visit = await factories.make_visit(
        db, society, flat, "DL8CAF5030", status=VisitStatus.PENDING_APPROVAL
    )
    event = (await post_read(client, entry_key, "DL8CAF5030")).json()["event"]
    assert event["match_result"] == "unknown"
    await db.refresh(visit)
    assert visit.status is VisitStatus.PENDING_APPROVAL


async def test_visitor_exit_closes_an_overstayed_visit(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society, flat: Flat, exit_key: str
) -> None:
    visit = await factories.make_visit(
        db, society, flat, "DL8CAF5030", status=VisitStatus.OVERSTAYED
    )
    event = (await post_read(client, exit_key, "DL8CAF5030")).json()["event"]
    assert event["match_result"] == "visitor"
    await db.refresh(visit)
    assert visit.status is VisitStatus.EXITED
    assert str(visit.exit_event_id) == event["id"]


async def test_unknown_vehicle_leaving_is_just_logged(
    client: httpx2.AsyncClient, exit_key: str
) -> None:
    event = (await post_read(client, exit_key, "MH12DE1433")).json()["event"]
    assert (event["match_result"], event["needs_review"]) == ("unknown", False)


# --- Snapshots ---------------------------------------------------------------------------


async def test_snapshot_is_stored_and_served_to_staff(
    client: httpx2.AsyncClient,
    entry_key: str,
    guard: User,
    snapshot_storage: LocalSnapshotStorage,
) -> None:
    event = (await post_read(client, entry_key, "DL01AB1234", snapshot=JPEG)).json()["event"]
    assert event["has_snapshot"] is True
    assert list(snapshot_storage.root.rglob("*.jpg"))  # really on disk

    image = await client.get(f"{URL}/{event['id']}/snapshot", headers=auth_headers(guard))
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/jpeg"
    assert image.content == JPEG


async def test_event_without_snapshot_has_no_image(
    client: httpx2.AsyncClient, entry_key: str, guard: User
) -> None:
    event = (await post_read(client, entry_key, "DL01AB1234")).json()["event"]
    assert event["has_snapshot"] is False
    image = await client.get(f"{URL}/{event['id']}/snapshot", headers=auth_headers(guard))
    assert image.status_code == 404


async def test_non_image_snapshot_is_refused(
    client: httpx2.AsyncClient, db: AsyncSession, entry_key: str
) -> None:
    response = await post_read(client, entry_key, "DL01AB1234", snapshot=b"<script>x</script>")
    assert response.status_code == 422
    assert await count_events(db) == 0


async def test_oversized_snapshot_is_refused(
    client: httpx2.AsyncClient, entry_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "snapshot_max_bytes", 32)
    response = await post_read(client, entry_key, "DL01AB1234", snapshot=JPEG)
    assert response.status_code == 413


# --- Review queue --------------------------------------------------------------------------


async def test_guard_correction_rematches_and_saves_labelled_data(
    client: httpx2.AsyncClient,
    db: AsyncSession,
    society: Society,
    flat: Flat,
    entry_key: str,
    guard: User,
) -> None:
    vehicle = await factories.make_vehicle(db, society, flat, "UP16AB1234")
    unsure = (await post_read(client, entry_key, "UP16A81Z34", confidence=0.5)).json()["event"]

    queue = await client.get(f"{URL}/review-queue", headers=auth_headers(guard))
    assert [item["id"] for item in queue.json()["items"]] == [unsure["id"]]

    response = await client.post(
        f"{URL}/{unsure['id']}/review",
        json={"action": "correct", "plate": "UP 16 AB 1234"},
        headers=auth_headers(guard),
    )
    reviewed = response.json()
    assert response.status_code == 200
    assert (reviewed["match_result"], reviewed["vehicle_id"]) == ("resident", str(vehicle.id))
    assert reviewed["reviewed_by_id"] == str(guard.id)
    assert reviewed["ocr_fixes"] is None  # the plate now comes from a person

    correction = await db.scalar(select(PlateCorrection))
    assert correction is not None
    assert (correction.original_plate, correction.corrected_plate) == ("UP16A81Z34", "UP16AB1234")

    queue = await client.get(f"{URL}/review-queue", headers=auth_headers(guard))
    assert queue.json()["total"] == 0


async def test_guard_correction_can_admit_a_visitor(
    client: httpx2.AsyncClient,
    db: AsyncSession,
    society: Society,
    flat: Flat,
    entry_key: str,
    guard: User,
) -> None:
    visit = await factories.make_visit(db, society, flat, "KA05MN0042")
    unsure = (await post_read(client, entry_key, "KA05MN0042", confidence=0.6)).json()["event"]
    await client.post(
        f"{URL}/{unsure['id']}/review",
        json={"action": "correct", "plate": "KA05MN0042"},
        headers=auth_headers(guard),
    )
    await db.refresh(visit)
    assert visit.status is VisitStatus.INSIDE


async def test_dismissing_a_review_item(
    client: httpx2.AsyncClient, db: AsyncSession, entry_key: str, guard: User
) -> None:
    item = (await post_read(client, entry_key, "????")).json()["event"]
    response = await client.post(
        f"{URL}/{item['id']}/review", json={"action": "dismiss"}, headers=auth_headers(guard)
    )
    assert response.status_code == 200
    assert response.json()["reviewed_at"] is not None
    assert await db.scalar(select(func.count()).select_from(PlateCorrection)) == 0


@pytest.mark.parametrize(
    "body",
    [
        {"action": "correct"},
        {"action": "dismiss", "plate": "DL01AB1234"},
        {"action": "approve"},
        {"action": "correct", "plate": "NOT A PLATE"},
    ],
)
async def test_bad_review_decisions_are_rejected(
    client: httpx2.AsyncClient, entry_key: str, guard: User, body: dict[str, str]
) -> None:
    item = (await post_read(client, entry_key, "DL01AB1234", confidence=0.1)).json()["event"]
    response = await client.post(
        f"{URL}/{item['id']}/review", json=body, headers=auth_headers(guard)
    )
    assert response.status_code == 422


async def test_an_item_is_reviewed_only_once(
    client: httpx2.AsyncClient, entry_key: str, guard: User, admin: User
) -> None:
    item = (await post_read(client, entry_key, "DL01AB1234", confidence=0.1)).json()["event"]
    url = f"{URL}/{item['id']}/review"
    assert (
        await client.post(url, json={"action": "dismiss"}, headers=auth_headers(guard))
    ).is_success
    again = await client.post(url, json={"action": "dismiss"}, headers=auth_headers(admin))
    assert again.status_code == 409


async def test_events_not_in_the_queue_cant_be_reviewed(
    client: httpx2.AsyncClient, entry_key: str, guard: User
) -> None:
    event = (await post_read(client, entry_key, "DL01AB1234")).json()["event"]
    response = await client.post(
        f"{URL}/{event['id']}/review", json={"action": "dismiss"}, headers=auth_headers(guard)
    )
    assert response.status_code == 409


async def test_other_societies_events_are_invisible(
    client: httpx2.AsyncClient, db: AsyncSession, entry_key: str
) -> None:
    event = (await post_read(client, entry_key, "DL01AB1234", confidence=0.1)).json()["event"]
    other = await factories.make_society(db, "Other Society")
    outsider = await factories.make_user(db, other, UserRole.GUARD, email="outsider@test.in")
    for path in (f"{URL}/{event['id']}", f"{URL}/{event['id']}/snapshot"):
        assert (await client.get(path, headers=auth_headers(outsider))).status_code == 404
    review = await client.post(
        f"{URL}/{event['id']}/review", json={"action": "dismiss"}, headers=auth_headers(outsider)
    )
    assert review.status_code == 404
    listing = await client.get(URL, headers=auth_headers(outsider))
    assert listing.json()["total"] == 0


# --- Listing and alerts --------------------------------------------------------------------


async def test_listing_filters(
    client: httpx2.AsyncClient,
    db: AsyncSession,
    society: Society,
    flat: Flat,
    entry_key: str,
    exit_key: str,
    guard: User,
) -> None:
    await factories.make_vehicle(db, society, flat, "UP16AB1234")
    await post_read(client, entry_key, "UP16AB1234", at=ago(50))
    await post_read(client, exit_key, "UP16AB1234", at=ago(40))
    await post_read(client, entry_key, "MH12DE1433", at=ago(30))
    headers = auth_headers(guard)

    everything = (await client.get(URL, headers=headers)).json()
    assert everything["total"] == 3
    assert [e["plate_normalized"] for e in everything["items"]][0] == "MH12DE1433"  # newest first

    async def total(**params: str) -> int:
        response = await client.get(URL, params=params, headers=headers)
        return int(response.json()["total"])

    assert await total(direction="exit") == 1
    assert await total(match_result="resident") == 2
    assert await total(q="mh12") == 1
    assert await total(needs_review="false") == 3
    assert await total(since=ago(45).isoformat()) == 2
    assert await total(until=ago(45).isoformat()) == 1


async def test_alerts_list_and_acknowledge(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society, entry_key: str, guard: User
) -> None:
    await factories.make_watchlist_entry(db, society, "HR26DK8337")
    await post_read(client, entry_key, "HR26DK8337")
    headers = auth_headers(guard)

    open_alerts = (await client.get("/api/v1/alerts?acknowledged=false", headers=headers)).json()
    assert open_alerts["total"] == 1
    alert_id = open_alerts["items"][0]["id"]

    first = await client.post(f"/api/v1/alerts/{alert_id}/acknowledge", headers=headers)
    second = await client.post(f"/api/v1/alerts/{alert_id}/acknowledge", headers=headers)
    assert first.json()["acknowledged_by_id"] == str(guard.id)
    assert second.json()["acknowledged_at"] == first.json()["acknowledged_at"]

    assert (await client.get("/api/v1/alerts?acknowledged=false", headers=headers)).json()[
        "total"
    ] == 0
    assert (await client.get("/api/v1/alerts?acknowledged=true", headers=headers)).json()[
        "total"
    ] == 1
    assert (await client.get("/api/v1/alerts", headers=headers)).json()["total"] == 1


async def test_unknown_car_never_creates_a_visit_by_itself(
    client: httpx2.AsyncClient, db: AsyncSession, entry_key: str
) -> None:
    await post_read(client, entry_key, "DL01AB1234")
    # Registering the visitor is the guard's job (Phase 4).
    assert await db.scalar(select(func.count()).select_from(Visit)) == 0


async def test_confirming_a_watchlist_read_doesnt_alert_twice(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society, entry_key: str, guard: User
) -> None:
    await factories.make_watchlist_entry(db, society, "HR26DK8337")
    item = (await post_read(client, entry_key, "HR26DK8337", confidence=0.4)).json()["event"]
    reviewed = await client.post(
        f"{URL}/{item['id']}/review",
        json={"action": "correct", "plate": "HR26DK8337"},
        headers=auth_headers(guard),
    )
    assert reviewed.json()["match_result"] == "watchlist"
    assert await db.scalar(select(func.count()).select_from(Alert)) == 1
    assert await db.scalar(select(func.count()).select_from(PlateCorrection)) == 1


async def test_filter_by_gate(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society, guard: User
) -> None:
    main, back = (
        await factories.make_gate(db, society),
        await factories.make_gate(db, society, "Back"),
    )
    _, main_key = await factories.make_device(db, main)
    _, back_key = await factories.make_device(db, back)
    await post_read(client, main_key, "DL01AB1234")
    await post_read(client, back_key, "DL01AB1235")
    response = await client.get(URL, params={"gate_id": str(back.id)}, headers=auth_headers(guard))
    assert [e["plate_normalized"] for e in response.json()["items"]] == ["DL01AB1235"]


async def test_simultaneous_identical_uploads_store_one_event(
    client: httpx2.AsyncClient,
    db: AsyncSession,
    entry_key: str,
    monkeypatch: pytest.MonkeyPatch,
    snapshot_storage: LocalSnapshotStorage,
) -> None:
    """Two copies of one read arrive together: both pass the duplicate check, one insert wins.

    We play the "other request" by inserting the winning row right after this request's
    duplicate check (from inside the debounce step, which runs between check and insert).
    """
    from app.services import debounce, gate_events

    at = ago(3)
    original = debounce.check_and_mark
    winner_id = uuid.uuid4()

    async def other_request_wins(*args: object, **kwargs: object) -> uuid.UUID | None:
        device = await db.scalar(select(Device))
        assert device is not None
        gate = await db.get(Gate, device.gate_id)
        assert gate is not None
        db.add(
            GateEvent(
                id=winner_id,
                society_id=gate.society_id,
                gate_id=device.gate_id,
                device_id=device.id,
                direction=device.direction,
                plate_raw="DL01AB1234",
                confidence=0.95,
                captured_at=at,
                event_hash=gate_events.event_hash(device.id, "DL01AB1234", at),
                match_result=MatchResult.UNKNOWN,
            )
        )
        await db.commit()
        return await original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(debounce, "check_and_mark", other_request_wins)
    response = await post_read(client, entry_key, "DL01AB1234", at=at, snapshot=JPEG)

    assert response.status_code == 200
    assert response.json()["status"] == "duplicate"
    assert response.json()["event"]["id"] == str(winner_id)
    # (No row count here: in tests both "requests" share one connection, so the winner's
    # row is rolled back with the request. In production they are separate transactions.)
    assert not list(snapshot_storage.root.rglob("*.jpg"))  # the loser's snapshot was removed


class FlakyStorage(LocalSnapshotStorage):
    """Fails the first save, like object storage that is restarting."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.failures_left = 1

    async def save(self, key: str, data: bytes, content_type: str) -> None:
        if self.failures_left:
            self.failures_left -= 1
            raise OSError("storage unavailable")
        await super().save(key, data, content_type)


async def test_a_retry_after_a_failed_save_is_a_new_read_not_debounced(
    client: httpx2.AsyncClient, entry_key: str, tmp_path: Path, db: AsyncSession
) -> None:
    """A read that fails while being stored must not leave its plate "seen just now":
    the camera's retry would then be debounced, and the car never logged."""
    storage = FlakyStorage(tmp_path)
    app.dependency_overrides[get_snapshot_storage] = lambda: storage
    at = ago(1)
    with pytest.raises(OSError, match="storage unavailable"):  # the API answers 500
        await post_read(client, entry_key, "UP16AB1234", at=at, snapshot=JPEG)

    retry = await post_read(client, entry_key, "UP16AB1234", at=at, snapshot=JPEG)

    assert retry.status_code == 201, retry.text
    assert retry.json()["status"] == "created"
    assert await db.scalar(select(func.count()).select_from(GateEvent)) == 1
