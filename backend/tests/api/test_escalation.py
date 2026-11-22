"""Phase 5 "done when": with the clock mocked, an overstaying visit moves through every
escalation step exactly once."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import (
    Approval,
    EscalationTask,
    Flat,
    Notification,
    Society,
    User,
    Visit,
    Visitor,
    VisitStatusChange,
)
from app.models.enums import (
    ApprovalStatus,
    EscalationOutcome,
    EscalationTaskStatus,
    LaneDirection,
    VisitStatus,
    VisitTrigger,
)
from app.services import escalation
from tests import factories
from tests.factories import auth_headers

LIMIT = datetime(2026, 11, 22, 14, 0, tzinfo=UTC)  # the visit's time limit


async def inside_visit(
    db: AsyncSession, society: Society, flat: Flat, *, email: str | None = "rohit@example.com"
) -> Visit:
    visitor = Visitor(
        society_id=society.id, full_name="Rohit Verma", phone="+919876543210", email=email
    )
    db.add(visitor)
    await db.flush()
    visit = Visit(
        society_id=society.id,
        flat_id=flat.id,
        visitor_id=visitor.id,
        plate_normalized="MH12DE1433",
        category="guest",
        status=VisitStatus.INSIDE,
        entered_at=LIMIT - timedelta(hours=4),
        expected_exit_at=LIMIT,
    )
    db.add(visit)
    await db.commit()
    return visit


async def notifications(db: AsyncSession) -> list[tuple[str, str]]:
    rows = await db.scalars(
        select(Notification).order_by(Notification.created_at, Notification.kind)
    )
    return sorted((n.kind, n.recipient) for n in rows)


async def history(db: AsyncSession, visit: Visit) -> list[VisitTrigger | None]:
    rows = await db.scalars(
        select(VisitStatusChange)
        .where(VisitStatusChange.visit_id == visit.id)
        .order_by(VisitStatusChange.changed_at)
    )
    return [r.trigger for r in rows]


async def tick(
    db: AsyncSession, redis: Redis, minutes_after_limit: float
) -> escalation.LadderResult:
    return await escalation.run_ladder(
        db, redis, get_settings(), LIMIT + timedelta(minutes=minutes_after_limit)
    )


async def test_overstay_moves_through_every_step_exactly_once(
    db: AsyncSession, redis_client: Redis, society: Society, flat: Flat, resident: User
) -> None:
    visit = await inside_visit(db, society, flat)

    # Before the limit: nothing.
    assert (await tick(db, redis_client, -1)).__dict__ == {
        "overstayed": 0,
        "emails_queued": 0,
        "escalated": 0,
    }

    # Step 1, at the limit: OVERSTAYED, visitor and resident emailed. Repeating does nothing.
    assert (await tick(db, redis_client, 0)).__dict__ == {
        "overstayed": 1,
        "emails_queued": 2,
        "escalated": 0,
    }
    assert (await tick(db, redis_client, 0.5)).__dict__ == {
        "overstayed": 0,
        "emails_queued": 0,
        "escalated": 0,
    }
    await db.refresh(visit)
    assert visit.status is VisitStatus.OVERSTAYED
    assert await notifications(db) == [
        ("overstay_notice", "resident@test.in"),
        ("overstay_notice", "rohit@example.com"),
    ]

    # Step 2, +30 min: a reminder to both, once.
    assert (await tick(db, redis_client, 29)).emails_queued == 0
    assert (await tick(db, redis_client, 30)).emails_queued == 2
    assert (await tick(db, redis_client, 45)).emails_queued == 0

    # Step 3, +60 min: ESCALATED and one guard task, once.
    assert (await tick(db, redis_client, 59)).escalated == 0
    assert (await tick(db, redis_client, 60)).escalated == 1
    for minutes in (61, 90, 240):
        assert (await tick(db, redis_client, minutes)).__dict__ == {
            "overstayed": 0,
            "emails_queued": 0,
            "escalated": 0,
        }

    after = await db.get(Visit, visit.id, populate_existing=True)
    assert after is not None and after.status is VisitStatus.ESCALATED
    assert await history(db, visit) == [VisitTrigger.OVERSTAY, VisitTrigger.ESCALATE]
    assert await db.scalar(select(func.count()).select_from(EscalationTask)) == 1
    kinds = [kind for kind, _ in await notifications(db)]
    assert kinds == ["overstay_notice"] * 2 + ["overstay_reminder"] * 2


async def test_one_late_run_catches_up_every_step_once(
    db: AsyncSession, redis_client: Redis, society: Society, flat: Flat, resident: User
) -> None:
    visit = await inside_visit(db, society, flat)
    result = await tick(db, redis_client, 95)  # the scheduler was down for an hour and a half
    assert result.__dict__ == {"overstayed": 1, "emails_queued": 4, "escalated": 1}
    assert (await tick(db, redis_client, 96)).__dict__ == {
        "overstayed": 0,
        "emails_queued": 0,
        "escalated": 0,
    }
    assert await history(db, visit) == [VisitTrigger.OVERSTAY, VisitTrigger.ESCALATE]


async def test_visitor_without_email_still_escalates(
    db: AsyncSession, redis_client: Redis, society: Society, flat: Flat, resident: User
) -> None:
    await inside_visit(db, society, flat, email=None)
    assert (await tick(db, redis_client, 0)).emails_queued == 1  # just the resident
    assert (await tick(db, redis_client, 60)).escalated == 1


async def test_visit_that_left_in_time_is_left_alone(
    db: AsyncSession, redis_client: Redis, society: Society, flat: Flat, resident: User
) -> None:
    visit = await inside_visit(db, society, flat)
    visit.status = VisitStatus.EXITED
    visit.exited_at = LIMIT - timedelta(minutes=5)
    await db.commit()
    assert (await tick(db, redis_client, 120)).__dict__ == {
        "overstayed": 0,
        "emails_queued": 0,
        "escalated": 0,
    }


async def escalated(
    db: AsyncSession, redis: Redis, society: Society, flat: Flat
) -> tuple[Visit, str]:
    visit = await inside_visit(db, society, flat)
    await tick(db, redis, 60)
    task = await db.scalar(select(EscalationTask).where(EscalationTask.visit_id == visit.id))
    assert task is not None
    return visit, str(task.id)


async def test_guard_resolves_the_call_task(
    client: httpx2.AsyncClient,
    db: AsyncSession,
    redis_client: Redis,
    society: Society,
    flat: Flat,
    guard: User,
    resident: User,
) -> None:
    visit, task_id = await escalated(db, redis_client, society, flat)
    listing = (
        await client.get("/api/v1/escalations?status=open", headers=auth_headers(guard))
    ).json()
    assert [t["id"] for t in listing["items"]] == [task_id]
    assert listing["items"][0]["visit"]["flat_label"] == "B-402"

    response = await client.post(
        f"/api/v1/escalations/{task_id}/resolve",
        json={"outcome": "reached", "notes": "Resident says the guest is leaving in 10 min"},
        headers=auth_headers(guard),
    )
    assert response.status_code == 200
    assert (response.json()["status"], response.json()["outcome"]) == ("resolved", "reached")
    assert response.json()["visit"]["status"] == "escalated"  # still inside
    again = await client.post(
        f"/api/v1/escalations/{task_id}/resolve",
        json={"outcome": "reached"},
        headers=auth_headers(guard),
    )
    assert again.status_code == 409


async def test_vehicle_left_closes_the_visit(
    client: httpx2.AsyncClient,
    db: AsyncSession,
    redis_client: Redis,
    society: Society,
    flat: Flat,
    guard: User,
    resident: User,
) -> None:
    visit, task_id = await escalated(db, redis_client, society, flat)
    response = await client.post(
        f"/api/v1/escalations/{task_id}/resolve",
        json={"outcome": "vehicle_left"},
        headers=auth_headers(guard),
    )
    assert response.json()["visit"]["status"] == "exited"


async def test_exit_camera_closes_the_open_task(
    client: httpx2.AsyncClient,
    db: AsyncSession,
    redis_client: Redis,
    society: Society,
    flat: Flat,
    resident: User,
) -> None:
    visit, task_id = await escalated(db, redis_client, society, flat)
    gate = await factories.make_gate(db, society)
    _, key = await factories.make_device(db, gate, LaneDirection.EXIT)
    read = await client.post(
        "/api/v1/gate-events",
        data={"plate_text": "MH12DE1433", "confidence": "0.95"},
        headers={"X-Device-Key": key},
    )
    assert read.json()["event"]["match_result"] == "visitor"
    task = await db.get(EscalationTask, uuid.UUID(task_id))
    await db.refresh(task)
    assert task is not None
    assert (task.status, task.outcome) == (
        EscalationTaskStatus.RESOLVED,
        EscalationOutcome.VEHICLE_LEFT,
    )


async def test_resident_cant_see_escalations(client: httpx2.AsyncClient, resident: User) -> None:
    assert (
        await client.get("/api/v1/escalations", headers=auth_headers(resident))
    ).status_code == 403


async def test_sweeper_times_out_approvals_whose_job_was_lost(
    client: httpx2.AsyncClient,
    db: AsyncSession,
    redis_client: Redis,
    guard: User,
    resident: User,
    flat: Flat,
) -> None:
    registered = await client.post(
        "/api/v1/visits",
        json={"full_name": "Rohit Verma", "phone": "9876543210", "flat_id": str(flat.id)},
        headers=auth_headers(guard),
    )
    approval_id = uuid.UUID(registered.json()["approval"]["id"])
    assert await escalation.sweep_approvals(db, redis_client) == 0
    later = datetime.now(UTC) + timedelta(minutes=4)
    assert (
        await escalation.sweep_approvals(db, redis_client, now=later) == 0
    )  # expire_approval uses the real clock

    approval = await db.get(Approval, approval_id)
    assert approval is not None
    approval.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    assert await escalation.sweep_approvals(db, redis_client) == 1
    await db.refresh(approval)
    assert approval.status is ApprovalStatus.TIMED_OUT


@pytest.mark.parametrize(
    "task",
    ["escalation.tick", "notifications.dispatch", "reconciliation.nightly", "retention.daily"],
)
def test_beat_schedule_runs_every_job(task: str) -> None:
    import app.workers.tasks  # noqa: F401 - a worker imports this module to register the tasks
    from app.workers.celery_app import celery_app

    assert task in celery_app.tasks
    assert task in {entry["task"] for entry in celery_app.conf.beat_schedule.values()}
