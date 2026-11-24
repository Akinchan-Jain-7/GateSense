"""The simulated society: cars coming and going, visitors, guest passes, a guard and
residents who answer (or don't), all through the real API.

Everything is scheduled on a small timeline (a heap of future actions), so one visit is a
chain of steps: the camera reads the plate, the guard registers the visitor, the resident
answers, the visitor leaves later (sometimes late enough to trigger the escalation
ladder, which the real Celery workers then run).
"""

import heapq
import itertools
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from gatesense_sim.api import Api, ApiError
from gatesense_sim.plates import misread, random_plate, snapshot_jpeg

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

FIRST = [
    "Rahul",
    "Imran",
    "Sunil",
    "Deepak",
    "Mohit",
    "Arjun",
    "Salman",
    "Vikas",
    "Rajesh",
    "Sanjay",
    "Neha",
    "Pooja",
    "Ritu",
    "Anjali",
    "Kavya",
    "Farhan",
    "Gurpreet",
    "Meera",
]
LAST = [
    "Kumar",
    "Khan",
    "Yadav",
    "Chauhan",
    "Saini",
    "Rawat",
    "Ali",
    "Pal",
    "Sharma",
    "Verma",
    "Gupta",
    "Singh",
    "Iyer",
    "Nair",
]
PURPOSES = {
    "delivery": ["Swiggy order", "Zomato order", "Amazon parcel", "Blinkit delivery", "Zepto"],
    "cab": ["Uber pickup", "Ola pickup", "Rapido drop"],
    "guest": ["Family visit", "Friends for dinner", "Tuition", "Birthday party"],
    "service": ["Electrician", "Plumber", "AC service", "Pest control"],
}
# Minutes a visitor normally stays, by category.
USUAL_STAY = {"delivery": (4, 14), "cab": (2, 8), "guest": (25, 110), "service": (30, 80)}
LIMITS = {"delivery": 20, "cab": 10, "guest": 240, "service": 60}
# Arrivals per minute at each hour of the day (IST): busy mornings and evenings.
RATE = [
    *(0.2, 0.1, 0.1, 0.1, 0.1, 0.2, 0.6, 1.4, 2.0, 1.6, 1.0, 1.0),  # midnight to noon
    *(1.4, 1.4, 1.0, 1.0, 1.2, 1.6, 2.2, 2.4, 2.0, 1.4, 0.8, 0.4),  # noon to midnight
]


@dataclass(order=True)
class Action:
    at: float
    seq: int
    name: str = field(compare=False)
    run: Callable[[], None] = field(compare=False)


@dataclass
class Society:
    entry_keys: list[str]
    exit_keys: list[str]
    vehicles: dict[str, str]  # plate -> flat id
    residents: dict[str, list[str]]  # flat id -> resident emails
    watchlist: list[str]
    inside: set[str] = field(default_factory=set)


class World:
    def __init__(
        self,
        api: Api,
        *,
        admin_email: str,
        guard_email: str,
        speed: float = 1.0,
        rng: random.Random | None = None,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        leave_devices: tuple[str, ...] = ("Laptop webcam",),
    ) -> None:
        self.api = api
        # Cameras whose name starts with one of these belong to a real camera (the laptop
        # webcam demo, docs/webcam-demo.md): their keys are left alone, and no simulated
        # traffic is sent under their name.
        self.leave_devices = leave_devices
        self.admin = admin_email
        self.guard = guard_email
        self.speed = speed
        self.rng = rng or random.Random()  # noqa: S311 - demo traffic, not security
        self.clock = clock
        self.now = now
        self.queue: list[Action] = []
        self.counter = itertools.count()
        self.society: Society | None = None
        self.last_watchlist = -1e9

    # --- setup --------------------------------------------------------------------

    def bootstrap(self) -> Society:
        """Fresh camera keys, the society's cars, residents and watchlist."""
        self.api.tokens.clear()
        self.queue.clear()
        entry: list[str] = []
        exit_: list[str] = []
        for device in self.api.all_pages(self.admin, "/api/v1/devices", is_active=True):
            if str(device.get("name", "")).startswith(self.leave_devices):
                continue
            key = self.api.call(self.admin, "POST", f"/api/v1/devices/{device['id']}/rotate-key")
            (entry if device["direction"] == "entry" else exit_).append(key["api_key"])
        vehicles = {
            v["plate_normalized"]: v["flat"]["id"]
            for v in self.api.all_pages(self.admin, "/api/v1/vehicles", is_active=True)
        }
        residents: dict[str, list[str]] = {}
        for r in self.api.all_pages(self.admin, "/api/v1/residents", is_active=True):
            residents.setdefault(r["flat"]["id"], []).append(r["user"]["email"])
        watchlist = [
            w["plate_normalized"]
            for w in self.api.all_pages(self.admin, "/api/v1/watchlist", is_active=True)
        ]
        # Assume residents' cars start at home (the demo seed leaves most of them inside).
        self.society = Society(entry, exit_, vehicles, residents, watchlist, set(vehicles))
        self.every(60, "housekeeping", self.housekeeping)
        logger.info(
            "bootstrapped: %d cameras, %d cars, %d flats with residents",
            len(entry) + len(exit_),
            len(vehicles),
            len(residents),
        )
        return self.society

    # --- timeline -----------------------------------------------------------------

    def later(
        self, seconds: float, name: str, run: Callable[[], None], *, wall_clock: bool = False
    ) -> None:
        """Run `run` after `seconds` of simulated time (or real time, for the server's own
        timers such as the approval timeout, which SIM_SPEED can't compress)."""
        at = self.clock() + (seconds if wall_clock else seconds / self.speed)
        heapq.heappush(self.queue, Action(at, next(self.counter), name, run))

    def every(self, seconds: float, name: str, run: Callable[[], None]) -> None:
        def repeat() -> None:
            run()
            self.later(seconds, name, repeat)

        self.later(seconds, name, repeat)

    def run_due(self) -> int:
        done = 0
        while self.queue and self.queue[0].at <= self.clock():
            action = heapq.heappop(self.queue)
            try:
                action.run()
            except ApiError as error:  # one failed step shouldn't stop the demo
                logger.warning("%s failed: %s", action.name, error)
            done += 1
        return done

    def tick(self, seconds: float) -> int:
        """Start new arrivals for the next `seconds`, at today's rate."""
        hour = self.now().astimezone(IST).hour
        expected = RATE[hour] * self.speed * seconds / 60
        arrivals = sum(1 for _ in range(10) if self.rng.random() < expected / 10)
        for _ in range(arrivals):
            self.arrival()
        return arrivals

    def arrival(self) -> None:
        roll = self.rng.random()
        if roll < 0.5:
            self.resident_moves()
        elif roll < 0.8:
            self.visitor()
        elif roll < 0.87:
            self.guest_pass()
        elif roll < 0.97:
            self.unsure_read()
        else:
            self.watchlisted_car()

    # --- helpers ------------------------------------------------------------------

    @property
    def s(self) -> Society:
        if self.society is None:
            raise RuntimeError("bootstrap() first")
        return self.society

    def camera(self, direction: str) -> str:
        return self.rng.choice(self.s.entry_keys if direction == "entry" else self.s.exit_keys)

    def read(
        self, direction: str, plate: str, confidence: float | None = None
    ) -> dict[str, object]:
        conf = confidence if confidence is not None else self.rng.uniform(0.86, 0.99)
        result = self.api.read(self.camera(direction), plate, conf, snapshot_jpeg(plate))
        event = result.get("event")
        return event if isinstance(event, dict) else {}

    def person(self) -> tuple[str, str]:
        name = f"{self.rng.choice(FIRST)} {self.rng.choice(LAST)}"
        phone = f"{self.rng.choice('6789')}{self.rng.randint(10**8, 10**9 - 1)}"
        return name, phone

    def flat_with_residents(self) -> tuple[str, list[str]]:
        flat_id = self.rng.choice(sorted(self.s.residents))
        return flat_id, self.s.residents[flat_id]

    def new_plate(self) -> str:
        while (plate := random_plate(self.rng)) in self.s.vehicles:
            pass
        return plate

    # --- scenarios ----------------------------------------------------------------

    def resident_moves(self) -> None:
        plate = self.rng.choice(sorted(self.s.vehicles))
        if plate in self.s.inside:
            self.read("exit", plate)
            self.s.inside.discard(plate)
        else:
            self.read("entry", plate)
            self.s.inside.add(plate)

    def visitor(self) -> None:
        category = self.rng.choices(["delivery", "cab", "guest", "service"], [5, 3, 3, 1])[0]
        plate = self.new_plate()
        event = self.read("entry", plate)
        self.later(
            self.rng.uniform(5, 15), "register", lambda: self.register(category, plate, event)
        )

    def register(self, category: str, plate: str, event: dict[str, object]) -> None:
        flat_id, emails = self.flat_with_residents()
        name, phone = self.person()
        body: dict[str, object] = {
            "full_name": name,
            "phone": phone,
            "flat_id": flat_id,
            "plate": plate,
            "category": category,
            "purpose": self.rng.choice(PURPOSES[category]),
            "gate_event_id": event.get("id"),
        }
        if category == "service":
            body["duration_minutes"] = LIMITS["service"]
        registered = self.api.call(self.guard, "POST", "/api/v1/visits", json=body)
        approval_id = registered["approval"]["id"]
        visit_id = registered["visit"]["id"]
        resident = self.rng.choice(emails)
        roll = self.rng.random()
        if roll < 0.72:
            self.later(
                self.rng.uniform(15, 90),
                "approve",
                lambda: self.answer(resident, approval_id, "approve", category, plate),
            )
        elif roll < 0.8:
            self.later(
                self.rng.uniform(15, 60),
                "deny",
                lambda: self.answer(resident, approval_id, "deny", category, plate),
            )
        else:  # nobody answers: after the 3-minute timeout the guard decides
            self.later(
                200,
                "guard decides",
                lambda: self.guard_decides(visit_id, category, plate),
                wall_clock=True,
            )

    def answer(
        self, resident: str, approval_id: str, decision: str, category: str, plate: str
    ) -> None:
        self.api.call(
            resident,
            "POST",
            f"/api/v1/approvals/{approval_id}/decision",
            json={"decision": decision},
        )
        if decision == "approve":
            self.schedule_exit(category, plate)

    def guard_decides(self, visit_id: str, category: str, plate: str) -> None:
        self.api.call(
            self.guard, "POST", f"/api/v1/visits/{visit_id}/decision", json={"decision": "approve"}
        )
        self.schedule_exit(category, plate)

    def schedule_exit(self, category: str, plate: str) -> None:
        low, high = USUAL_STAY[category]
        minutes = self.rng.uniform(low, high)
        if self.rng.random() < 0.08:  # stays too long: the escalation ladder kicks in
            minutes = LIMITS[category] + self.rng.uniform(15, 75)

        def leave() -> None:
            self.read("exit", plate)

        self.later(minutes * 60, "visitor leaves", leave)

    def guest_pass(self) -> None:
        flat_id, emails = self.flat_with_residents()
        plate = self.new_plate()
        name, phone = self.person()
        start = self.now()
        self.api.call(
            self.rng.choice(emails),
            "POST",
            "/api/v1/guest-passes",
            json={
                "guest_name": name,
                "guest_phone": phone,
                "plate": plate,
                "with_code": False,
                "valid_from": start.isoformat(),
                "valid_until": (start + timedelta(hours=3)).isoformat(),
                "max_uses": 1,
                "category": "guest",
            },
        )

        def arrive() -> None:
            self.read("entry", plate)
            self.schedule_exit("guest", plate)

        self.later(self.rng.uniform(30, 120), "guest arrives", arrive)

    def unsure_read(self) -> None:
        plate = self.rng.choice(sorted(self.s.vehicles))
        self.read("entry", misread(plate, self.rng), confidence=self.rng.uniform(0.45, 0.72))
        self.s.inside.add(plate)

    def watchlisted_car(self) -> None:
        if not self.s.watchlist or self.clock() - self.last_watchlist < 2700 / self.speed:
            self.visitor()  # at most one watchlist alert every 45 minutes
            return
        self.last_watchlist = self.clock()
        self.read("entry", self.rng.choice(self.s.watchlist))

    # --- the guard's chores ---------------------------------------------------------

    def housekeeping(self) -> None:
        """The simulated guard clears old items, so the console shows a living mix: new
        things stay a few minutes for visitors of the demo to see, then get handled."""
        now = self.now()

        def older_than(item: dict[str, object], minutes: float) -> bool:
            created = datetime.fromisoformat(str(item.get("created_at") or item["received_at"]))
            return now - created > timedelta(minutes=minutes / self.speed)

        tasks = self.api.call(self.guard, "GET", "/api/v1/escalations", params={"status": "open"})
        for task in tasks["items"]:
            if older_than(task, 8):
                outcome = self.rng.choice(["reached", "reached", "vehicle_left", "not_reached"])
                self.api.call(
                    self.guard,
                    "POST",
                    f"/api/v1/escalations/{task['id']}/resolve",
                    json={"outcome": outcome},
                )
        alerts = self.api.call(self.guard, "GET", "/api/v1/alerts", params={"acknowledged": False})
        for alert in alerts["items"]:
            if older_than(alert, 5):
                self.api.call(self.guard, "POST", f"/api/v1/alerts/{alert['id']}/acknowledge")
        for event in self.api.call(self.guard, "GET", "/api/v1/gate-events/review-queue")["items"]:
            if older_than(event, 3) and event.get("plate_normalized"):
                self.api.call(
                    self.guard,
                    "POST",
                    f"/api/v1/gate-events/{event['id']}/review",
                    json={"action": "correct", "plate": event["plate_normalized"]},
                )
