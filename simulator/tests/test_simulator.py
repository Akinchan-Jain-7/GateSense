"""The simulator against a fake API: bootstrap, each scenario, the guard's chores, and
starting over after a demo reset."""

import json
import random
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from gatesense_sim import __main__ as cli
from gatesense_sim.api import Api, ApiError, NeedsBootstrapError
from gatesense_sim.plates import misread, random_plate, snapshot_jpeg
from gatesense_sim.world import World

PLATE = re.compile(r"^[A-Z]{2}\d{2}[A-Z]{1,2}\d{4}$")
NOW = datetime(2026, 11, 22, 13, 30, tzinfo=UTC)  # 7 pm IST: rush hour


def page(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"items": items, "total": len(items)}


class FakeApi:
    """Records every call; answers like the GateSense API."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.reads: list[dict[str, str]] = []
        self.valid_keys = {"key-entry", "key-exit"}
        self.logins = 0
        self.expired_tokens: set[str] = set()
        old = (NOW - timedelta(minutes=30)).isoformat()
        self.open_tasks = [{"id": "t1", "created_at": old}]

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        body: dict[str, Any] = {}
        if request.headers.get("content-type", "").startswith("application/json"):
            body = json.loads(request.content)
        self.calls.append((method, path, body))
        if path == "/api/v1/auth/login":
            self.logins += 1
            tokens = {"access_token": f"tok{self.logins}", "refresh_token": "r"}
            return httpx.Response(200, json=tokens)
        if path == "/api/v1/auth/refresh":
            return httpx.Response(200, json={"access_token": "fresh", "refresh_token": "r2"})
        if path == "/api/v1/gate-events" and method == "POST":
            if request.headers["X-Device-Key"] not in self.valid_keys:
                return httpx.Response(401, json={"detail": "bad key"})
            text = request.content.decode(errors="replace")
            plate = text.split('name="plate_text"\r\n\r\n')[1].split("\r\n")[0]
            self.reads.append({"plate": plate, "key": request.headers["X-Device-Key"]})
            event = {"id": f"e{len(self.reads)}"}
            return httpx.Response(201, json={"status": "created", "event": event})
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token in self.expired_tokens:
            return httpx.Response(401, json={"detail": "expired"})
        return httpx.Response(200, json=self.answer(method, path))

    def answer(self, method: str, path: str) -> Any:
        if path == "/api/v1/devices":
            return page(
                [
                    {"id": "d1", "name": "Main Gate - entry camera", "direction": "entry"},
                    {"id": "d2", "name": "Main Gate - exit camera", "direction": "exit"},
                    {"id": "d3", "name": "Laptop webcam - entry", "direction": "entry"},
                ]
            )
        if path.endswith("/rotate-key"):
            return {"api_key": "key-entry" if "d1" in path else "key-exit"}
        if path == "/api/v1/vehicles":
            return page([{"plate_normalized": "UP16AB1234", "flat": {"id": "f1"}}])
        if path == "/api/v1/residents":
            return page([{"flat": {"id": "f1"}, "user": {"email": "priya@example.com"}}])
        if path == "/api/v1/watchlist":
            return page([{"plate_normalized": "HR26DK8337"}])
        if path == "/api/v1/visits" and method == "POST":
            return {"visit": {"id": "v1"}, "approval": {"id": "a1"}}
        if path == "/api/v1/escalations":
            return page(self.open_tasks)
        if path in ("/api/v1/alerts", "/api/v1/gate-events/review-queue"):
            return page([])
        return {}


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def fake() -> FakeApi:
    return FakeApi()


def world_for(fake: FakeApi, clock: Clock | None = None, seed: int = 1) -> World:
    api = Api("http://api.test", "GateSense@123", transport=httpx.MockTransport(fake.handler))
    return World(
        api,
        admin_email="admin@example.com",
        guard_email="guard@example.com",
        rng=random.Random(seed),
        clock=clock or Clock(),
        now=lambda: NOW,
    )


def test_plates_look_real() -> None:
    rng = random.Random(3)
    plates = [random_plate(rng) for _ in range(200)]
    assert all(PLATE.match(p) for p in plates)
    assert not any(set(p[4:-4]) & set("IOQ") for p in plates)  # no I, O, Q in the series
    assert misread("UP16AB1050", random.Random(1)) != "UP16AB1050"
    assert snapshot_jpeg("UP16AB1234")[:3] == b"\xff\xd8\xff"


def test_bootstrap_rotates_keys_and_loads_the_society(fake: FakeApi) -> None:
    society = world_for(fake).bootstrap()
    assert society.entry_keys == ["key-entry"]
    assert society.exit_keys == ["key-exit"]
    assert society.vehicles == {"UP16AB1234": "f1"}
    assert society.residents == {"f1": ["priya@example.com"]}
    assert society.inside == {"UP16AB1234"}  # cars start at home


def test_bootstrap_leaves_the_laptop_webcam_alone(fake: FakeApi) -> None:
    """Rotating its key would break a webcam demo running next to the simulator."""
    world_for(fake).bootstrap()
    rotated = [path for _, path, _ in fake.calls if path.endswith("/rotate-key")]
    assert rotated == ["/api/v1/devices/d1/rotate-key", "/api/v1/devices/d2/rotate-key"]


def test_a_resident_car_leaves_then_comes_back(fake: FakeApi) -> None:
    world = world_for(fake)
    world.bootstrap()
    world.resident_moves()
    world.resident_moves()
    assert [(r["plate"], r["key"]) for r in fake.reads] == [
        ("UP16AB1234", "key-exit"),
        ("UP16AB1234", "key-entry"),
    ]


@pytest.mark.parametrize("seed", range(6))
def test_a_visitor_is_read_registered_answered_and_leaves(fake: FakeApi, seed: int) -> None:
    clock = Clock()
    world = world_for(fake, clock, seed=seed)
    world.speed = 10  # the approval timeout still takes its full 3 real minutes
    world.bootstrap()
    world.visitor()
    assert fake.reads[0]["key"] == "key-entry"
    plate = fake.reads[0]["plate"]

    clock.t += 3
    world.run_due()  # the guard registers the visitor
    registration = next(c for c in fake.calls if c[:2] == ("POST", "/api/v1/visits"))
    assert registration[2]["plate"] == plate
    assert registration[2]["gate_event_id"] == "e1"
    assert registration[2]["flat_id"] == "f1"

    clock.t += 10
    world.run_due()  # the resident may have answered by now; the guard can't decide yet
    early = [c for c in fake.calls if c[1].endswith("/decision")]
    assert all(c[1].startswith("/api/v1/approvals/") for c in early)

    clock.t += 200
    world.run_due()  # the resident answered, or the guard decided after the timeout
    decisions = [c for c in fake.calls if c[1].endswith("/decision")]
    assert len(decisions) == 1

    clock.t += 3600
    world.run_due()  # long after: an approved visitor has left through an exit camera
    if decisions[0][2]["decision"] == "approve":
        assert fake.reads[-1] == {"plate": plate, "key": "key-exit"}
    else:
        assert len(fake.reads) == 1  # turned away: never came in, never leaves


def test_guest_pass_unsure_read_and_watchlist(fake: FakeApi) -> None:
    clock = Clock()
    world = world_for(fake, clock)
    world.bootstrap()
    world.guest_pass()
    assert any(c[1] == "/api/v1/guest-passes" for c in fake.calls)
    clock.t += 200
    world.run_due()  # the guest arrives
    world.unsure_read()
    world.watchlisted_car()
    world.watchlisted_car()  # minutes later: becomes an ordinary visitor instead
    plates = [r["plate"] for r in fake.reads]
    assert plates.count("HR26DK8337") == 1
    assert any(p != "UP16AB1234" and p.startswith("UP16AB") for p in plates)  # the misread


def test_the_guard_handles_old_call_tasks(fake: FakeApi) -> None:
    world = world_for(fake)
    world.bootstrap()
    world.housekeeping()
    assert any(c[1] == "/api/v1/escalations/t1/resolve" for c in fake.calls)


def test_rush_hour_brings_arrivals(fake: FakeApi) -> None:
    world = world_for(fake, seed=5)
    world.bootstrap()
    assert sum(world.tick(60) for _ in range(30)) > 20  # about 2.4 a minute at 7 pm


def test_expired_sessions_are_refreshed_before_signing_in_again(fake: FakeApi) -> None:
    world = world_for(fake)
    world.bootstrap()
    logins = fake.logins
    fake.expired_tokens.add("tok1")
    world.api.call("admin@example.com", "GET", "/api/v1/devices")
    assert fake.logins == logins  # refreshed, not a new login
    assert ("POST", "/api/v1/auth/refresh", {"refresh_token": "r"}) in fake.calls


def test_a_reset_demo_means_starting_over(fake: FakeApi) -> None:
    world = world_for(fake)
    world.bootstrap()
    fake.valid_keys = set()  # the demo reset rotated every camera key
    with pytest.raises(NeedsBootstrapError):
        world.resident_moves()


def test_one_failing_step_does_not_stop_the_rest(fake: FakeApi) -> None:
    clock = Clock()
    world = world_for(fake, clock)
    ran: list[str] = []

    def broken() -> None:
        raise ApiError(409, "already decided")

    world.later(1, "broken", broken)
    world.later(2, "fine", lambda: ran.append("fine"))
    clock.t = 5
    assert world.run_due() == 2
    assert ran == ["fine"]


def test_cli_runs_for_a_while_and_stops(monkeypatch: pytest.MonkeyPatch, fake: FakeApi) -> None:
    real_init = Api.__init__

    def init(self: Api, base_url: str, password: str, **_: object) -> None:
        real_init(self, base_url, password, transport=httpx.MockTransport(fake.handler))

    monkeypatch.setattr(Api, "__init__", init)
    ticks = iter(range(100_000))
    fake_time = SimpleNamespace(sleep=lambda _: None, monotonic=lambda: next(ticks) * 1.0)
    monkeypatch.setattr(cli, "time", fake_time)
    assert cli.main(["--minutes", "0.5", "--seed", "1", "--tick", "1"]) == 0
    assert fake.logins >= 1
