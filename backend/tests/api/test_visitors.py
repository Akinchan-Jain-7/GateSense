"""Visitor registration, resident approvals, the timeout and the guard fallback."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Approval, Flat, GateEvent, Society, User, Visit, VisitStatusChange
from app.models.enums import ApprovalStatus, LaneDirection, UserRole, VisitStatus, VisitTrigger
from app.services import visitors
from tests import factories
from tests.conftest import RecordingJobs
from tests.factories import auth_headers

VISITS = "/api/v1/visits"


def registration(flat: Flat, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "full_name": "Rohit Verma",
        "phone": "98765 43210",
        "email": "rohit@example.com",
        "flat_id": str(flat.id),
        "category": "guest",
        "purpose": "Family visit",
        "plate": "MH12DE1433",
    }
    return body | overrides


async def register(
    client: httpx2.AsyncClient, guard: User, flat: Flat, **overrides: Any
) -> dict[str, Any]:
    response = await client.post(
        VISITS, json=registration(flat, **overrides), headers=auth_headers(guard)
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def decide(
    client: httpx2.AsyncClient, user: User, approval_id: str, decision: str
) -> httpx2.Response:
    return await client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": decision},
        headers=auth_headers(user),
    )


async def force_timeout(db: AsyncSession, approval_id: str) -> None:
    approval = await db.get(Approval, uuid.UUID(approval_id))
    assert approval is not None
    approval.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()


# --- Registration ---------------------------------------------------------------------------


async def test_guard_registers_a_visitor_and_residents_are_asked(
    client: httpx2.AsyncClient,
    guard: User,
    flat: Flat,
    resident: User,
    jobs: RecordingJobs,
    db: AsyncSession,
) -> None:
    body = await register(client, guard, flat)
    visit, approval = body["visit"], body["approval"]

    assert visit["status"] == "pending_approval"
    assert (visit["flat_label"], visit["visitor_name"], visit["plate_normalized"]) == (
        "B-402",
        "Rohit Verma",
        "MH12DE1433",
    )
    assert visit["visitor_phone"] == "+91 98•••••210"  # masked in API output
    assert approval["status"] == "pending"
    expires = datetime.fromisoformat(approval["expires_at"]) - datetime.fromisoformat(
        approval["requested_at"]
    )
    assert expires == timedelta(minutes=3)
    # The timeout job and the Telegram notification were scheduled.
    assert [str(a) for a, _ in jobs.timeouts] == [approval["id"]]
    assert [str(a) for a in jobs.notifications] == [approval["id"]]
    history = (
        await db.scalars(
            select(VisitStatusChange).where(VisitStatusChange.visit_id == uuid.UUID(visit["id"]))
        )
    ).all()
    assert [(h.from_status, h.to_status) for h in history] == [(None, VisitStatus.PENDING_APPROVAL)]


async def test_repeat_visitors_are_recognised_by_phone(
    client: httpx2.AsyncClient, guard: User, flat: Flat, resident: User, db: AsyncSession
) -> None:
    first = await register(client, guard, flat)
    second = await register(client, guard, flat, full_name="Rohit K. Verma", phone="+919876543210")
    a = await db.get(Visit, uuid.UUID(first["visit"]["id"]))
    b = await db.get(Visit, uuid.UUID(second["visit"]["id"]))
    assert a is not None and b is not None and a.visitor_id == b.visitor_id
    assert second["visit"]["visitor_name"] == "Rohit K. Verma"


@pytest.mark.parametrize(
    "overrides",
    [
        {"phone": "12345"},
        {"phone": "5876543210"},  # Indian mobiles start with 6-9
        {"plate": "NOT A PLATE"},
        {"full_name": "R"},
        {"duration_minutes": 60},  # only for service visits
        {"category": "spaceship"},
    ],
)
async def test_bad_registrations_are_rejected(
    client: httpx2.AsyncClient, guard: User, flat: Flat, overrides: dict[str, Any]
) -> None:
    response = await client.post(
        VISITS, json=registration(flat, **overrides), headers=auth_headers(guard)
    )
    assert response.status_code == 422


async def test_flat_must_be_in_the_guards_society(
    client: httpx2.AsyncClient, guard: User, db: AsyncSession
) -> None:
    other = await factories.make_society(db, "Elsewhere")
    elsewhere = await factories.make_flat(db, other, "A", "101")
    response = await client.post(VISITS, json=registration(elsewhere), headers=auth_headers(guard))
    assert response.status_code == 404


async def test_flat_without_residents_goes_straight_to_the_guard(
    client: httpx2.AsyncClient, guard: User, flat: Flat, jobs: RecordingJobs
) -> None:
    body = await register(client, guard, flat)  # nobody lives in B-402 in this test
    assert body["approval"]["status"] == "timed_out"
    assert jobs.timeouts == [] and jobs.notifications == []
    decided = await client.post(
        f"{VISITS}/{body['visit']['id']}/decision",
        json={"decision": "approve"},
        headers=auth_headers(guard),
    )
    assert decided.json()["status"] == "approved"


# --- Resident decisions ------------------------------------------------------------------


async def test_resident_approves(
    client: httpx2.AsyncClient, guard: User, flat: Flat, resident: User, db: AsyncSession
) -> None:
    body = await register(client, guard, flat)
    response = await decide(client, resident, body["approval"]["id"], "approve")
    assert response.status_code == 200
    data = response.json()
    assert (data["status"], data["channel"], data["decided_by_id"]) == (
        "approved",
        "web",
        str(resident.id),
    )
    assert data["visit"]["status"] == "approved"  # no waiting car linked: stays approved
    assert data["visit"]["approved_by_id"] == str(resident.id)


async def test_resident_denies(
    client: httpx2.AsyncClient, guard: User, flat: Flat, resident: User
) -> None:
    body = await register(client, guard, flat)
    data = (await decide(client, resident, body["approval"]["id"], "deny")).json()
    assert (data["status"], data["visit"]["status"]) == ("denied", "denied")


async def test_deciding_twice_the_same_way_is_fine_changing_it_is_not(
    client: httpx2.AsyncClient,
    guard: User,
    flat: Flat,
    resident: User,
    society: Society,
    db: AsyncSession,
) -> None:
    flatmate = await factories.make_resident(db, society, flat, email="flatmate@test.in")
    body = await register(client, guard, flat)
    approval = body["approval"]["id"]
    assert (await decide(client, resident, approval, "approve")).status_code == 200
    again = await decide(client, flatmate, approval, "approve")
    assert again.status_code == 200
    assert again.json()["decided_by_id"] == str(resident.id)  # the first answer stands
    conflict = await decide(client, flatmate, approval, "deny")
    assert conflict.status_code == 409
    assert "Already decided: approved" in conflict.json()["detail"]


async def test_residents_of_other_flats_cant_decide(
    client: httpx2.AsyncClient,
    guard: User,
    flat: Flat,
    resident: User,
    society: Society,
    db: AsyncSession,
) -> None:
    body = await register(client, guard, flat)
    other_flat = await factories.make_flat(db, society, "C", "104")
    neighbour = await factories.make_resident(db, society, other_flat, email="neighbour@test.in")
    response = await decide(client, neighbour, body["approval"]["id"], "approve")
    assert response.status_code == 404
    listing = await client.get("/api/v1/approvals", headers=auth_headers(neighbour))
    assert listing.json()["total"] == 0


async def test_approval_admits_a_waiting_car_at_once(
    client: httpx2.AsyncClient,
    guard: User,
    flat: Flat,
    resident: User,
    society: Society,
    db: AsyncSession,
) -> None:
    gate = await factories.make_gate(db, society)
    _, key = await factories.make_device(db, gate, LaneDirection.ENTRY)
    read = await client.post(
        "/api/v1/gate-events",
        data={"plate_text": "MH12DE1433", "confidence": "0.95"},
        headers={"X-Device-Key": key},
    )
    event_id = read.json()["event"]["id"]
    assert read.json()["event"]["match_result"] == "unknown"

    body = await register(client, guard, flat, plate=None, gate_event_id=event_id)
    assert body["visit"]["plate_normalized"] == "MH12DE1433"  # taken from the read
    event = await db.get(GateEvent, uuid.UUID(event_id))
    await db.refresh(event)
    assert event is not None and event.match_result == "visitor"

    data = (await decide(client, resident, body["approval"]["id"], "approve")).json()
    assert data["visit"]["status"] == "inside"
    assert data["visit"]["entry_event_id"] == event_id
    assert data["visit"]["expected_exit_at"] is not None

    again = await client.post(
        VISITS, json=registration(flat, gate_event_id=event_id), headers=auth_headers(guard)
    )
    assert again.status_code == 409  # that read already belongs to a visit


async def test_exit_lane_reads_cant_be_linked(
    client: httpx2.AsyncClient, guard: User, flat: Flat, society: Society, db: AsyncSession
) -> None:
    gate = await factories.make_gate(db, society)
    _, key = await factories.make_device(db, gate, LaneDirection.EXIT)
    read = await client.post(
        "/api/v1/gate-events",
        data={"plate_text": "MH12DE1433", "confidence": "0.95"},
        headers={"X-Device-Key": key},
    )
    response = await client.post(
        VISITS,
        json=registration(flat, gate_event_id=read.json()["event"]["id"]),
        headers=auth_headers(guard),
    )
    assert response.status_code == 409


# --- Timeout and guard fallback -----------------------------------------------------------


async def test_guard_must_wait_for_the_residents(
    client: httpx2.AsyncClient, guard: User, flat: Flat, resident: User
) -> None:
    body = await register(client, guard, flat)
    early = await client.post(
        f"{VISITS}/{body['visit']['id']}/decision",
        json={"decision": "approve"},
        headers=auth_headers(guard),
    )
    assert early.status_code == 409
    assert "can still answer" in early.json()["detail"]


async def test_timeout_job_hands_over_to_the_guard(
    client: httpx2.AsyncClient,
    guard: User,
    flat: Flat,
    resident: User,
    db: AsyncSession,
    redis_client: Redis,
) -> None:
    body = await register(client, guard, flat)
    approval_id = uuid.UUID(body["approval"]["id"])

    assert await visitors.expire_approval(db, redis_client, approval_id) is False  # not due yet
    await force_timeout(db, str(approval_id))
    assert await visitors.expire_approval(db, redis_client, approval_id) is True
    assert await visitors.expire_approval(db, redis_client, approval_id) is False  # idempotent

    late = await decide(client, resident, str(approval_id), "approve")
    assert late.status_code == 409
    decided = await client.post(
        f"{VISITS}/{body['visit']['id']}/decision",
        json={"decision": "deny"},
        headers=auth_headers(guard),
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "denied"
    history = (
        await db.scalars(
            select(VisitStatusChange)
            .where(VisitStatusChange.visit_id == uuid.UUID(body["visit"]["id"]))
            .order_by(VisitStatusChange.changed_at)
        )
    ).all()
    assert history[-1].trigger is VisitTrigger.DENY and history[-1].actor_id == guard.id


async def test_late_resident_answer_marks_the_timeout_itself(
    client: httpx2.AsyncClient, guard: User, flat: Flat, resident: User, db: AsyncSession
) -> None:
    body = await register(client, guard, flat)
    await force_timeout(db, body["approval"]["id"])  # the job hasn't run yet
    late = await decide(client, resident, body["approval"]["id"], "approve")
    assert late.status_code == 409
    assert "timed out" in late.json()["detail"]
    approval = await db.get(Approval, uuid.UUID(body["approval"]["id"]))
    await db.refresh(approval)
    assert approval is not None and approval.status is ApprovalStatus.TIMED_OUT


async def test_guard_decision_needs_a_pending_visit(
    client: httpx2.AsyncClient, guard: User, flat: Flat, resident: User
) -> None:
    body = await register(client, guard, flat)
    await decide(client, resident, body["approval"]["id"], "approve")
    response = await client.post(
        f"{VISITS}/{body['visit']['id']}/decision",
        json={"decision": "deny"},
        headers=auth_headers(guard),
    )
    assert response.status_code == 409


# --- Manual entry/exit and lists ------------------------------------------------------------


async def test_guard_marks_entry_and_exit_by_hand(
    client: httpx2.AsyncClient, guard: User, flat: Flat, resident: User
) -> None:
    body = await register(client, guard, flat, category="delivery")
    await decide(client, resident, body["approval"]["id"], "approve")
    visit_id = body["visit"]["id"]
    entered = (await client.post(f"{VISITS}/{visit_id}/enter", headers=auth_headers(guard))).json()
    assert entered["status"] == "inside"
    limit = datetime.fromisoformat(entered["expected_exit_at"]) - datetime.fromisoformat(
        entered["entered_at"]
    )
    assert limit == timedelta(minutes=20)  # delivery
    assert (
        await client.post(f"{VISITS}/{visit_id}/enter", headers=auth_headers(guard))
    ).status_code == 409
    exited = (await client.post(f"{VISITS}/{visit_id}/exit", headers=auth_headers(guard))).json()
    assert exited["status"] == "exited"


async def test_service_visit_uses_the_agreed_duration(
    client: httpx2.AsyncClient, guard: User, flat: Flat, resident: User
) -> None:
    body = await register(
        client, guard, flat, category="service", duration_minutes=90, purpose="AC repair"
    )
    await decide(client, resident, body["approval"]["id"], "approve")
    entered = (
        await client.post(f"{VISITS}/{body['visit']['id']}/enter", headers=auth_headers(guard))
    ).json()
    limit = datetime.fromisoformat(entered["expected_exit_at"]) - datetime.fromisoformat(
        entered["entered_at"]
    )
    assert limit == timedelta(minutes=90)


async def test_lists_for_staff_and_residents(
    client: httpx2.AsyncClient,
    guard: User,
    flat: Flat,
    resident: User,
    society: Society,
    db: AsyncSession,
) -> None:
    other_flat = await factories.make_flat(db, society, "C", "104")
    neighbour = await factories.make_resident(db, society, other_flat, email="neighbour@test.in")
    mine = await register(client, guard, flat)
    await register(
        client, guard, other_flat, phone="9123456780", full_name="Anita Rao", plate="KA05MN0042"
    )

    staff = (await client.get(VISITS, headers=auth_headers(guard))).json()
    assert staff["total"] == 2
    own = (await client.get(VISITS, headers=auth_headers(resident))).json()
    assert [v["id"] for v in own["items"]] == [mine["visit"]["id"]]
    pending = (
        await client.get("/api/v1/approvals?status=pending", headers=auth_headers(resident))
    ).json()
    assert pending["total"] == 1
    assert pending["items"][0]["visit"]["visitor_name"] == "Rohit Verma"

    async def total(**params: str) -> int:
        return int(
            (await client.get(VISITS, params=params, headers=auth_headers(guard))).json()["total"]
        )

    assert await total(q="anita") == 1
    assert await total(q="ka05") == 1
    assert await total(status="pending_approval") == 2
    assert await total(inside="true") == 0
    assert await total(flat_id=str(flat.id)) == 1
    other = await client.get(f"{VISITS}/{mine['visit']['id']}", headers=auth_headers(neighbour))
    assert other.status_code == 404


async def test_resident_role_cant_register(
    client: httpx2.AsyncClient, resident: User, flat: Flat
) -> None:
    response = await client.post(VISITS, json=registration(flat), headers=auth_headers(resident))
    assert response.status_code == 403
    assert resident.role is UserRole.RESIDENT
