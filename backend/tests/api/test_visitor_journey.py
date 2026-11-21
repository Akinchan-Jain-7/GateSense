"""Phase 4 "done when": the full unknown-visitor path, end to end, through the real API.

unknown car at the entry camera
  -> guard registers the visitor against that read
  -> the resident is asked live (WebSocket) and on Telegram
  -> the resident taps Approve on Telegram -> the waiting car is admitted
  -> the exit camera reads the plate -> the visit is closed
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx2
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Flat, Society, User, Visit, VisitStatusChange
from app.models.enums import LaneDirection, VisitStatus, VisitTrigger
from app.services import visitors
from app.workers.tasks import send_approval
from tests import factories
from tests.api.test_telegram_and_realtime import FakeBot, Socket, link, press, token_for, webhook
from tests.conftest import RecordingJobs
from tests.factories import auth_headers

pytest_plugins = ["tests.api.test_telegram_and_realtime"]  # the `bot` fixture


async def camera(
    client: httpx2.AsyncClient, key: str, plate: str, at: datetime
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/gate-events",
        data={"plate_text": plate, "confidence": "0.94", "captured_at": at.isoformat()},
        headers={"X-Device-Key": key},
    )
    assert response.status_code == 201, response.text
    event: dict[str, object] = response.json()["event"]
    return event


async def test_unknown_visitor_end_to_end(
    client: httpx2.AsyncClient,
    db: AsyncSession,
    society: Society,
    flat: Flat,
    guard: User,
    resident: User,
    jobs: RecordingJobs,
    bot: FakeBot,
) -> None:
    gate = await factories.make_gate(db, society)
    _, entry_key = await factories.make_device(db, gate, LaneDirection.ENTRY)
    _, exit_key = await factories.make_device(db, gate, LaneDirection.EXIT)
    await link(client, resident, chat_id=555)
    t0 = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=30)
    state: dict[str, object] = {}

    # (Sockets are opened one after the other: in tests all sessions share one database
    # connection, so two handshakes at the same instant would interleave their savepoints.)
    async with Socket(f"/api/v1/ws?token={token_for(guard)}") as console:
        await console.receive()  # accept
        await console.receive_json()  # hello
        async with Socket(f"/api/v1/ws?token={token_for(resident)}") as phone:
            await phone.receive()
            await phone.receive_json()
            await asyncio.sleep(0.05)
            await _journey(client, entry_key, flat, guard, jobs, db, bot, console, phone, t0, state)

    event = state["event"]
    visit_id = state["visit_id"]
    assert isinstance(event, dict) and isinstance(visit_id, uuid.UUID)

    # 5. Later the exit camera reads the plate (with an OCR slip): the visit is closed.
    exit_read = await camera(client, exit_key, "MH12DEI433", datetime.now(UTC))
    assert (exit_read["match_result"], exit_read["visit_id"]) == ("visitor", str(visit_id))

    visit = await db.get(Visit, visit_id)
    await db.refresh(visit)
    assert visit is not None
    assert visit.status is VisitStatus.EXITED
    assert str(visit.entry_event_id) == event["id"]
    assert str(visit.exit_event_id) == exit_read["id"]
    assert visit.approved_by_id == resident.id
    assert visit.expected_exit_at is not None and visit.entered_at is not None
    assert visit.expected_exit_at - visit.entered_at == timedelta(hours=4)

    history = (
        await db.scalars(
            select(VisitStatusChange)
            .where(VisitStatusChange.visit_id == visit_id)
            .order_by(VisitStatusChange.changed_at, VisitStatusChange.to_status)
        )
    ).all()
    assert [(h.trigger, h.to_status) for h in history] == [
        (None, VisitStatus.PENDING_APPROVAL),
        (VisitTrigger.APPROVE, VisitStatus.APPROVED),
        (VisitTrigger.ENTER, VisitStatus.INSIDE),
        (VisitTrigger.EXIT, VisitStatus.EXITED),
    ]


async def _journey(
    client: httpx2.AsyncClient,
    entry_key: str,
    flat: Flat,
    guard: User,
    jobs: RecordingJobs,
    db: AsyncSession,
    bot: FakeBot,
    console: Socket,
    phone: Socket,
    t0: datetime,
    state: dict[str, object],
) -> None:
    # 1. An unknown car stops at the barrier; the guard console shows it.
    event = await camera(client, entry_key, "MH12DE1433", t0)
    assert event["match_result"] == "unknown"
    shown = await console.receive_json()
    assert (shown["type"], shown["data"]["id"]) == ("gate_event.created", event["id"])

    # 2. The guard registers the driver against that read.
    registered = await client.post(
        "/api/v1/visits",
        json={
            "full_name": "Rohit Verma",
            "phone": "98765 43210",
            "email": "rohit@example.com",
            "flat_id": str(flat.id),
            "purpose": "Family visit",
            "gate_event_id": event["id"],
        },
        headers=auth_headers(guard),
    )
    assert registered.status_code == 201
    approval_id = registered.json()["approval"]["id"]
    visit_id = uuid.UUID(registered.json()["visit"]["id"])

    # 3. The resident's phone gets the request live; the console sees it too.
    asked = await phone.receive_json()
    assert (asked["type"], asked["data"]["id"]) == ("approval.requested", approval_id)
    assert (await console.receive_json())["type"] == "approval.requested"
    assert [str(a) for a, _ in jobs.timeouts] == [approval_id]

    # ...and on Telegram (the job the API scheduled, run here directly).
    assert await send_approval(db, get_settings(), bot, uuid.UUID(approval_id)) == 1  # type: ignore[arg-type]

    # 4. The resident taps Approve in Telegram: the waiting car is admitted at once.
    assert (await webhook(client, press(555, approval_id, "a"))).json()["result"] == "decided"
    decided = await phone.receive_json()
    assert decided["type"] == "approval.decided"
    assert decided["data"]["visit"]["status"] == "inside"
    assert decided["data"]["channel"] == "telegram"
    state.update(event=event, visit_id=visit_id)


async def test_nobody_answers_and_the_guard_decides(
    client: httpx2.AsyncClient,
    db: AsyncSession,
    redis_client: Redis,
    society: Society,
    flat: Flat,
    guard: User,
    resident: User,
) -> None:
    gate = await factories.make_gate(db, society)
    _, entry_key = await factories.make_device(db, gate, LaneDirection.ENTRY)
    event = await camera(client, entry_key, "KA05MN0042", datetime.now(UTC) - timedelta(minutes=5))
    registered = await client.post(
        "/api/v1/visits",
        json={
            "full_name": "Swiggy rider",
            "phone": "9000000002",
            "flat_id": str(flat.id),
            "category": "delivery",
            "gate_event_id": event["id"],
        },
        headers=auth_headers(guard),
    )
    approval_id = uuid.UUID(registered.json()["approval"]["id"])
    visit_id = registered.json()["visit"]["id"]

    # Three minutes pass; the timeout job runs.
    from app.models import Approval

    approval = await db.get(Approval, approval_id)
    assert approval is not None
    approval.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    assert await visitors.expire_approval(db, redis_client, approval_id)

    decided = await client.post(
        f"/api/v1/visits/{visit_id}/decision",
        json={"decision": "approve"},
        headers=auth_headers(guard),
    )
    assert decided.status_code == 200
    body = decided.json()
    assert (body["status"], body["approved_by_id"]) == ("inside", str(guard.id))
    limit = datetime.fromisoformat(body["expected_exit_at"]) - datetime.fromisoformat(
        body["entered_at"]
    )
    assert limit == timedelta(minutes=20)  # delivery


def test_celery_tasks_are_registered_and_the_runner_works(
    database_url: str, monkeypatch: object
) -> None:
    """Workers run async services in a fresh loop with their own engine (app/workers/runner.py)."""
    import pytest
    from sqlalchemy import text

    from app.workers.celery_app import celery_app
    from app.workers.runner import run_job

    assert {"approvals.expire", "approvals.telegram"} <= set(celery_app.tasks)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(get_settings(), "database_url", database_url)

        async def job(db: AsyncSession, redis: Redis, settings: object) -> int:
            return int(await db.scalar(text("SELECT 41 + 1")) or 0)

        assert run_job(job) == 42
        assert run_job(job) == 42  # a second task gets a fresh loop and engine
