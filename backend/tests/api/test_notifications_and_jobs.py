"""Email notifications, visitor links, reconciliation and the retention purge."""

import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

import httpx2
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import create_token
from app.models import (
    Flat,
    GateEvent,
    GuestPass,
    Notification,
    ReconciliationFlag,
    Society,
    User,
    Visit,
    Visitor,
)
from app.models.enums import LaneDirection, MatchResult, NotificationStatus, VisitStatus
from app.services import emails, notifications, reconciliation, retention, visit_links
from app.services.storage import LocalSnapshotStorage
from tests import factories
from tests.factories import auth_headers

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


class FakeMailer:
    def __init__(self, fail_times: int = 0) -> None:
        self.sent: list[tuple[str, emails.Email]] = []
        self.fail_times = fail_times

    async def send(self, to: str, email: emails.Email) -> None:
        if self.fail_times:
            self.fail_times -= 1
            raise ConnectionError("SMTP server not reachable")
        self.sent.append((to, email))


async def queue(db: AsyncSession, society: Society, key: str = "test:1") -> bool:
    email = emails.overstay_notice("Priya", "Rohit", "B-402", NOW, to_visitor=False)
    new = await notifications.queue_email(
        db, society_id=society.id, kind="overstay_notice", to="p@test.in", email=email, key=key
    )
    await db.commit()
    return new


# --- Notifications -------------------------------------------------------------------------


async def test_queueing_is_idempotent(db: AsyncSession, society: Society) -> None:
    assert await queue(db, society) is True
    assert await queue(db, society) is False
    assert await db.scalar(select(func.count()).select_from(Notification)) == 1


async def test_dispatcher_sends_once(db: AsyncSession, society: Society) -> None:
    await queue(db, society)
    mailer = FakeMailer()
    assert await notifications.dispatch_due(db, mailer, get_settings(), NOW) == {
        "sent": 1,
        "retrying": 0,
        "failed": 0,
        "cancelled": 0,
    }
    assert await notifications.dispatch_due(db, mailer, get_settings(), NOW) == {
        "sent": 0,
        "retrying": 0,
        "failed": 0,
        "cancelled": 0,
    }
    ((to, email),) = mailer.sent
    assert to == "p@test.in"
    assert email.subject == "Visit time is up (B-402)"
    assert "Rohit was due to leave by 5:30 PM, 22 Nov" in email.text  # Indian time


async def test_failed_sends_retry_with_backoff_then_give_up(
    db: AsyncSession, society: Society
) -> None:
    await queue(db, society)
    mailer = FakeMailer(fail_times=10)
    settings = get_settings()
    first = await notifications.dispatch_due(db, mailer, settings, NOW)
    assert first == {"sent": 0, "retrying": 1, "failed": 0, "cancelled": 0}
    note = await db.scalar(select(Notification))
    assert note is not None
    assert note.next_attempt_at == NOW + timedelta(minutes=1)
    assert note.last_error == "ConnectionError: SMTP server not reachable"
    # Not due yet: nothing happens.
    assert (await notifications.dispatch_due(db, mailer, settings, NOW + timedelta(seconds=30)))[
        "retrying"
    ] == 0

    at = NOW
    for _ in range(settings.notification_max_attempts - 1):
        at += timedelta(hours=2)
        await notifications.dispatch_due(db, mailer, settings, at)
    await db.refresh(note)
    assert (note.status, note.attempts) == (
        NotificationStatus.FAILED,
        settings.notification_max_attempts,
    )


def test_backoff_doubles_up_to_an_hour() -> None:
    assert [notifications.backoff(n).total_seconds() / 60 for n in range(1, 9)] == [
        1,
        2,
        4,
        8,
        16,
        32,
        60,
        60,
    ]


async def test_a_retry_that_works_is_sent(db: AsyncSession, society: Society) -> None:
    await queue(db, society)
    mailer = FakeMailer(fail_times=1)
    await notifications.dispatch_due(db, mailer, get_settings(), NOW)
    assert (
        await notifications.dispatch_due(db, mailer, get_settings(), NOW + timedelta(minutes=2))
    )["sent"] == 1
    note = await db.scalar(select(Notification))
    assert note is not None and note.last_error is None and note.attempts == 2


async def test_smtp_mailer_sends_text_and_html(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[EmailMessage] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            assert (host, port) == ("127.0.0.1", 1025)

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def send_message(self, message: EmailMessage) -> None:
            sent.append(message)

    monkeypatch.setattr(notifications.smtplib, "SMTP", FakeSMTP)  # type: ignore[attr-defined]
    email = emails.visit_welcome("<b>Rohit</b>", "B-402", NOW, "http://x/visit/t")
    await notifications.SmtpMailer(get_settings()).send("rohit@example.com", email)
    (message,) = sent
    assert message["To"] == "rohit@example.com"
    assert message["Subject"] == "Welcome! Your visit to B-402 ends at 5:30 PM, 22 Nov"
    html = message.get_body(("html",))
    assert html is not None and "&lt;b&gt;Rohit&lt;/b&gt;" in html.get_content()  # escaped
    plain = message.get_body(("plain",))
    assert plain is not None and "http://x/visit/t" in plain.get_content()


async def test_entering_queues_a_welcome_email_with_a_working_link(
    client: httpx2.AsyncClient, db: AsyncSession, guard: User, resident: User, flat: Flat
) -> None:
    registered = await client.post(
        "/api/v1/visits",
        json={
            "full_name": "Rohit Verma",
            "phone": "9876543210",
            "email": "rohit@example.com",
            "flat_id": str(flat.id),
        },
        headers=auth_headers(guard),
    )
    approval_id = registered.json()["approval"]["id"]
    await client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": "approve"},
        headers=auth_headers(resident),
    )
    await client.post(
        f"/api/v1/visits/{registered.json()['visit']['id']}/enter", headers=auth_headers(guard)
    )

    note = await db.scalar(select(Notification).where(Notification.kind == "visit_welcome"))
    assert note is not None and note.recipient == "rohit@example.com"
    link = next(word for word in (note.body_text or "").split() if "/visit/" in word)
    token = link.rsplit("/", 1)[1]
    view = await client.get(f"/api/v1/public/visits/{token}")
    assert view.status_code == 200
    body = view.json()
    assert (body["first_name"], body["flat_label"], body["status"]) == ("Rohit", "B-402", "inside")
    assert 4 * 3600 - 120 < body["seconds_remaining"] <= 4 * 3600
    assert "phone" not in str(body)

    page = await client.get(f"/visit/{token}")
    assert page.status_code == 200
    assert "Hi Rohit" in page.text and "time remaining" in page.text


# --- Visitor links -------------------------------------------------------------------------


async def test_bad_links_are_refused(
    client: httpx2.AsyncClient, admin: User, db: AsyncSession, society: Society, flat: Flat
) -> None:
    settings = get_settings()
    visit = Visit(
        society_id=society.id,
        flat_id=flat.id,
        category="guest",
        status=VisitStatus.INSIDE,
        expected_exit_at=NOW,
    )
    db.add(visit)
    await db.commit()
    expired = visit_links.make_token(settings, visit.id, datetime.now(UTC) - timedelta(hours=3))
    login_token, _ = create_token(settings, admin.id, "access")
    for token in (
        expired,
        "not.a.token",
        visit_links.make_token(settings, visit.id, NOW + timedelta(days=1))[:-2] + "xx",
        login_token,
    ):
        assert (await client.get(f"/api/v1/public/visits/{token}")).status_code == 404
    page = await client.get(f"/visit/{expired}")
    assert page.status_code == 404 and "no longer valid" in page.text
    # And a visitor link can't be used to log in.
    link = visit_links.make_token(settings, visit.id, NOW + timedelta(days=1))
    assert (
        await client.get("/api/v1/me", headers={"Authorization": f"Bearer {link}"})
    ).status_code == 401


# --- Reconciliation ----------------------------------------------------------------------


async def resident_event(
    db: AsyncSession,
    vehicle_id: uuid.UUID,
    society: Society,
    direction: LaneDirection,
    hours_ago: float,
    **extra: object,
) -> GateEvent:
    gate = await factories.make_gate(db, society, f"Gate {uuid.uuid4().hex[:4]}")
    device, _ = await factories.make_device(db, gate, direction)
    event = GateEvent(
        society_id=society.id,
        gate_id=gate.id,
        device_id=device.id,
        direction=direction,
        plate_raw="UP16AB1234",
        plate_normalized="UP16AB1234",
        confidence=0.95,
        captured_at=NOW - timedelta(hours=hours_ago),
        event_hash=uuid.uuid4().hex,
        match_result=MatchResult.RESIDENT,
        vehicle_id=vehicle_id,
        **extra,
    )
    db.add(event)
    await db.commit()
    return event


async def test_reconciliation_flags_each_problem_once(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society, flat: Flat, admin: User
) -> None:
    vehicle = await factories.make_vehicle(db, society, flat, "UP16AB1234")
    lonely_exit = await resident_event(db, vehicle.id, society, LaneDirection.EXIT, hours_ago=10)
    first_entry = await resident_event(db, vehicle.id, society, LaneDirection.ENTRY, hours_ago=8)
    await resident_event(
        db, vehicle.id, society, LaneDirection.ENTRY, hours_ago=5
    )  # open: parked at home
    stale = Visit(
        society_id=society.id,
        flat_id=flat.id,
        category="guest",
        status=VisitStatus.OVERSTAYED,
        expected_exit_at=NOW - timedelta(hours=30),
    )
    fresh = Visit(
        society_id=society.id,
        flat_id=flat.id,
        category="guest",
        status=VisitStatus.INSIDE,
        expected_exit_at=NOW - timedelta(hours=2),
    )
    db.add_all([stale, fresh])
    await db.commit()

    counts = await reconciliation.reconcile(db, get_settings(), NOW)
    assert counts == {"exit_without_entry": 1, "entry_never_closed": 1, "visit_not_closed": 1}
    assert await reconciliation.reconcile(db, get_settings(), NOW) == {
        "exit_without_entry": 0,
        "entry_never_closed": 0,
        "visit_not_closed": 0,
    }
    flags = {(f.kind.value, f.subject_id) for f in await db.scalars(select(ReconciliationFlag))}
    assert flags == {
        ("exit_without_entry", lonely_exit.id),
        ("entry_never_closed", first_entry.id),
        ("visit_not_closed", stale.id),
    }

    listing = (
        await client.get("/api/v1/reconciliation?resolved=false", headers=auth_headers(admin))
    ).json()
    assert listing["total"] == 3
    flag_id = listing["items"][0]["id"]
    assert (
        await client.post(f"/api/v1/reconciliation/{flag_id}/resolve", headers=auth_headers(admin))
    ).status_code == 200
    assert (
        await client.post(f"/api/v1/reconciliation/{flag_id}/resolve", headers=auth_headers(admin))
    ).status_code == 409
    assert (
        await client.get("/api/v1/reconciliation?resolved=false", headers=auth_headers(admin))
    ).json()["total"] == 2


async def test_a_just_arrived_exit_gets_a_grace_period(
    db: AsyncSession, society: Society, flat: Flat
) -> None:
    vehicle = await factories.make_vehicle(db, society, flat, "UP16AB1234")
    await resident_event(db, vehicle.id, society, LaneDirection.EXIT, hours_ago=0.2)
    assert (await reconciliation.reconcile(db, get_settings(), NOW))["exit_without_entry"] == 0


# --- Retention -----------------------------------------------------------------------------


async def test_retention_purge_removes_old_personal_data(
    db: AsyncSession, society: Society, flat: Flat, snapshot_storage: LocalSnapshotStorage
) -> None:
    long_ago = NOW - timedelta(days=120)
    old_visitor = Visitor(
        society_id=society.id, full_name="Old Visitor", phone="+919000000001", created_at=long_ago
    )
    recent_visitor = Visitor(
        society_id=society.id,
        full_name="Recent Visitor",
        phone="+919000000002",
        created_at=long_ago,
    )
    db.add_all([old_visitor, recent_visitor])
    await db.flush()
    db.add_all(
        [
            Visit(
                society_id=society.id,
                flat_id=flat.id,
                visitor_id=old_visitor.id,
                category="guest",
                status=VisitStatus.EXITED,
                created_at=long_ago,
            ),
            Visit(
                society_id=society.id,
                flat_id=flat.id,
                visitor_id=recent_visitor.id,
                category="guest",
                status=VisitStatus.EXITED,
                created_at=NOW - timedelta(days=3),
            ),
            GuestPass(
                society_id=society.id,
                flat_id=flat.id,
                guest_name="Priya Nair",
                guest_phone="+919000000003",
                category="guest",
                plate_normalized="KA05MN0042",
                valid_from=long_ago,
                valid_until=long_ago + timedelta(days=1),
                max_uses=1,
                use_count=1,
            ),
        ]
    )
    old_note = Notification(
        society_id=society.id,
        channel="email",
        kind="overstay_notice",
        recipient="old@test.in",
        subject="x",
        body_text="Hi Old Visitor",
        idempotency_key="old",
        created_at=long_ago,
    )
    db.add(old_note)
    gate = await factories.make_gate(db, society)
    device, _ = await factories.make_device(db, gate)
    await snapshot_storage.save("old/snap.jpg", b"\xff\xd8\xffold", "image/jpeg")
    event = GateEvent(
        society_id=society.id,
        gate_id=gate.id,
        device_id=device.id,
        direction=LaneDirection.ENTRY,
        plate_raw="X",
        confidence=0.9,
        captured_at=long_ago,
        event_hash="h-old",
        match_result=MatchResult.UNKNOWN,
        snapshot_path="old/snap.jpg",
    )
    db.add(event)
    await db.commit()

    counts = await retention.purge(db, snapshot_storage, get_settings(), NOW)
    assert counts == {"visitors": 1, "notifications": 1, "guest_passes": 1, "snapshots": 1}
    assert await retention.purge(db, snapshot_storage, get_settings(), NOW) == {
        "visitors": 0,
        "notifications": 0,
        "guest_passes": 0,
        "snapshots": 0,
    }

    names = set(await db.scalars(select(Visitor.full_name)))
    assert names == {"Recent Visitor"}  # visited 3 days ago: kept
    await db.refresh(old_note)
    assert (old_note.recipient, old_note.body_text) == ("redacted", None)
    assert (
        await db.scalar(select(func.count()).select_from(Visit)) == 2
    )  # visits stay for statistics
    await db.refresh(event)
    assert event.snapshot_path is None
    assert not (snapshot_storage.root / "old" / "snap.jpg").exists()
    guest_pass = await db.scalar(select(GuestPass))
    assert guest_pass is not None and (guest_pass.guest_name, guest_pass.guest_phone) == (
        "Guest",
        None,
    )


async def test_notification_log_for_admins(
    client: httpx2.AsyncClient, db: AsyncSession, society: Society, admin: User
) -> None:
    await queue(db, society)
    listing = (
        await client.get("/api/v1/notifications?status=pending", headers=auth_headers(admin))
    ).json()
    assert listing["total"] == 1
    assert listing["items"][0]["subject"] == "Visit time is up (B-402)"
