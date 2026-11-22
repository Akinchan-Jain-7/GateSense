"""Seed the database with realistic demo data.

    uv run python -m app.seed            # seed an empty database (no-op if already seeded)
    uv run python -m app.seed --reset    # wipe every table first, then seed
    uv run python -m app.seed --no-history   # skip the 14 days of past demo activity

Creates one society with 40 flats (blocks A-D), ~60 residents, ~80 vehicles, 3 guards,
1 admin, 2 gates with an entry and an exit camera each, and a few watchlist entries.
A fixed random seed makes every run produce the same data. All people are fictional;
emails use the reserved example.com domain.

Demo logins (password = DEMO_PASSWORD, default "GateSense@123"):
    admin@example.com · guard@example.com · resident@example.com
"""

import argparse
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import event_loop
from app.core.config import Settings, get_settings
from app.core.security import generate_device_key, hash_password
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.demo_history import FlatContacts, GateLanes, Lane, ResidentCar, add_history
from app.models import (
    Device,
    Flat,
    Gate,
    Resident,
    Society,
    User,
    Vehicle,
    WatchlistEntry,
)
from app.models.enums import LaneDirection, ResidentType, UserRole, VehicleType
from app.services import society_settings
from app.services.plates import normalize_typed_plate

RANDOM_SEED = 2026

DEMO_ADMIN_EMAIL = "admin@example.com"
DEMO_GUARD_EMAIL = "guard@example.com"
DEMO_RESIDENT_EMAIL = "resident@example.com"
DEMO_RESIDENT_FLAT = ("B", "402")

BLOCKS = ["A", "B", "C", "D"]
FLOORS = range(1, 6)
FLATS_PER_FLOOR = 2

FIRST_NAMES_F = [
    "Priya",
    "Ananya",
    "Kavya",
    "Neha",
    "Pooja",
    "Shreya",
    "Ishita",
    "Meera",
    "Aditi",
    "Riya",
    "Sneha",
    "Divya",
    "Nandini",
    "Tanvi",
    "Sakshi",
    "Aarti",
    "Swati",
    "Pallavi",
]
FIRST_NAMES_M = [
    "Rahul",
    "Amit",
    "Vikram",
    "Arjun",
    "Rohan",
    "Karan",
    "Siddharth",
    "Aditya",
    "Nikhil",
    "Varun",
    "Manish",
    "Deepak",
    "Saurabh",
    "Gaurav",
    "Harsh",
    "Kunal",
    "Yash",
    "Abhishek",
]
SURNAMES = [
    "Sharma",
    "Verma",
    "Gupta",
    "Agarwal",
    "Mehta",
    "Iyer",
    "Nair",
    "Reddy",
    "Singh",
    "Chauhan",
    "Joshi",
    "Kapoor",
    "Malhotra",
    "Bansal",
    "Saxena",
    "Mishra",
    "Pandey",
    "Bhatia",
    "Chopra",
    "Kulkarni",
    "Banerjee",
    "Das",
    "Khanna",
    "Tiwari",
    "Rao",
]

CARS = [
    "Maruti Swift",
    "Maruti Baleno",
    "Hyundai Creta",
    "Hyundai i20",
    "Tata Nexon",
    "Tata Punch EV",
    "Mahindra XUV700",
    "Mahindra Thar",
    "Honda City",
    "Kia Seltos",
    "Toyota Innova Crysta",
    "MG ZS EV",
    "Skoda Kushaq",
]
TWO_WHEELERS = [
    "Honda Activa 6G",
    "TVS Jupiter",
    "Royal Enfield Classic 350",
    "Bajaj Pulsar NS200",
    "Ather 450X",
    "Hero Splendor Plus",
    "Ola S1 Pro",
]
COLOURS = ["White", "Silver", "Grey", "Black", "Red", "Blue", "Brown"]

GUARDS = [
    ("Ramesh Yadav", DEMO_GUARD_EMAIL),
    ("Suresh Kumar", "suresh.kumar@example.com"),
    ("Mohan Singh Rawat", "mohan.rawat@example.com"),
]

WATCHLIST = [
    ("HR26DK8337", "Reported for rash driving inside the society; entry needs admin approval"),
    ("UP14FT4410", "Vendor contract ended; vehicle not permitted on the premises"),
    ("DL8CAF0921", "Linked to a theft complaint filed by a resident with the police"),
]


@dataclass
class SeedSummary:
    flats: int = 0
    residents: int = 0
    vehicles: int = 0
    guards: int = 0
    gates: int = 0
    devices: int = 0
    watchlist: int = 0
    history_visits: int = 0
    history_gate_events: int = 0
    # Plaintext device keys, printed once so you can try device auth in /docs.
    device_keys: dict[str, str] = field(default_factory=dict)


def _phone(rng: random.Random) -> str:
    return f"+91{rng.choice('6789')}{rng.randrange(10**8, 10**9)}"


def _plate(rng: random.Random, vehicle_type: VehicleType) -> str:
    """A realistic plate as people write it, e.g. 'UP16 AB 1234' or 'DL 3C AB 1234'."""
    letters = "ABCDEFGHJKLMNPRSTUVWXYZ"  # I, O and Q are not used in plate series
    series = "".join(rng.choices(letters, k=2))
    number = f"{rng.randrange(1, 10000):04d}"
    style = rng.choices(
        ["noida", "ghaziabad", "delhi", "haryana", "other", "bh"], weights=[40, 15, 25, 10, 5, 5]
    )[0]
    if style == "noida":
        return f"UP16 {series} {number}"
    if style == "ghaziabad":
        return f"UP14 {series} {number}"
    if style == "delhi":
        # Delhi adds a category letter after the district: C = car, S = scooter.
        category = "C" if vehicle_type == VehicleType.CAR else "S"
        return f"DL {rng.randrange(1, 13)}{category} {series} {number}"
    if style == "haryana":
        return f"HR{rng.choice(['26', '29', '51'])} {series} {number}"
    if style == "other":
        return f"{rng.choice(['MH12', 'KA05', 'RJ14', 'PB10'])} {series} {number}"
    return f"{rng.choice(['22', '23', '24', '25'])} BH {number} {series}"


async def reset_database(db: AsyncSession) -> None:
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    await db.execute(text(f"TRUNCATE {tables} CASCADE"))
    await db.commit()


async def is_seeded(db: AsyncSession) -> bool:
    return bool(await db.scalar(select(func.count()).select_from(Society)))


async def seed(
    db: AsyncSession,
    settings: Settings,
    *,
    history_days: int = 0,
    now: datetime | None = None,
    live: bool = False,
) -> SeedSummary:
    """Create the demo society. With `history_days`, also add that many days of past
    (closed) visits and gate reads ending at `now`; see app/demo_history.py."""
    rng = random.Random(RANDOM_SEED)  # noqa: S311 - demo data, not security
    summary = SeedSummary()
    # One hash for every demo account: they share the published demo password anyway,
    # and hashing 60+ times with Argon2 would make seeding slow.
    password_hash = hash_password(settings.demo_password)

    society = Society(name="Aravali Heights", address="Sector 150, Noida, Uttar Pradesh 201310")
    db.add(society)
    await db.flush()

    def user(name: str, email: str, role: UserRole) -> User:
        return User(
            society_id=society.id,
            email=email,
            full_name=name,
            phone=_phone(rng),
            role=role,
            password_hash=password_hash,
        )

    db.add(user("Anil Mehta", DEMO_ADMIN_EMAIL, UserRole.ADMIN))
    guards = [user(name, email, UserRole.GUARD) for name, email in GUARDS]
    db.add_all(guards)
    summary.guards = len(guards)
    residents_by_flat: dict[int, list[User]] = {}

    flats = [
        Flat(
            society_id=society.id,
            block=block,
            number=f"{floor}0{unit}",
            floor=floor,
            parking_slots=rng.choice([1, 1, 2]),
        )
        for block in BLOCKS
        for floor in FLOORS
        for unit in range(1, FLATS_PER_FLOOR + 1)
    ]
    db.add_all(flats)
    summary.flats = len(flats)

    # Half the flats have two residents (a couple or a family), the rest have one.
    two_resident_flats = set(rng.sample(range(len(flats)), k=len(flats) // 2))
    used_emails: set[str] = set()

    def resident_email(first: str, last: str) -> str:
        base = f"{first}.{last}".lower()
        email, n = f"{base}@example.com", 2
        while email in used_emails:
            email, n = f"{base}{n}@example.com", n + 1
        used_emails.add(email)
        return email

    for index, flat in enumerate(flats):
        surname = rng.choice(SURNAMES)
        people = [rng.choice(FIRST_NAMES_F + FIRST_NAMES_M)]
        if index in two_resident_flats:
            people.append(
                rng.choice(FIRST_NAMES_M if people[0] in FIRST_NAMES_F else FIRST_NAMES_F)
            )
        is_rented = rng.random() < 0.25
        for position, first in enumerate(people):
            is_demo = (flat.block, flat.number) == DEMO_RESIDENT_FLAT and position == 0
            if is_demo:
                first, surname = "Priya", "Sharma"
            email = DEMO_RESIDENT_EMAIL if is_demo else resident_email(first, surname)
            if position == 0:
                kind = ResidentType.TENANT if is_rented else ResidentType.OWNER
            else:
                kind = ResidentType.FAMILY
            resident_user = user(f"{first} {surname}", email, UserRole.RESIDENT)
            residents_by_flat.setdefault(index, []).append(resident_user)
            db.add(
                Resident(
                    user=resident_user,
                    flat=flat,
                    resident_type=kind,
                    is_primary_contact=position == 0,
                )
            )
            summary.residents += 1

    # Two vehicles per flat on average: 80 in total.
    used_plates: set[str] = set()
    vehicles: list[Vehicle] = []
    vehicle_counts = [2] * len(flats)
    for _ in range(len(flats) // 4):  # move some vehicles between flats: 1 to 3 each
        vehicle_counts[rng.randrange(len(flats))] -= 1
        vehicle_counts[rng.randrange(len(flats))] += 1
    for flat, count in zip(flats, vehicle_counts, strict=True):
        for _ in range(max(count, 0)):
            vehicle_type = VehicleType.CAR if rng.random() < 0.65 else VehicleType.TWO_WHEELER
            plate_raw = _plate(rng, vehicle_type)
            plate = normalize_typed_plate(plate_raw)
            if plate in used_plates:
                continue
            used_plates.add(plate)
            vehicles.append(
                Vehicle(
                    society_id=society.id,
                    flat=flat,
                    plate_raw=plate_raw,
                    plate_normalized=plate,
                    vehicle_type=vehicle_type,
                    make_model=rng.choice(
                        CARS if vehicle_type == VehicleType.CAR else TWO_WHEELERS
                    ),
                    colour=rng.choice(COLOURS),
                )
            )
    db.add_all(vehicles)
    summary.vehicles = len(vehicles)

    lanes: dict[str, dict[LaneDirection, Device]] = {}
    for gate_name, location in [
        ("Main Gate", "Sector 150 main road, towards the expressway"),
        ("Service Gate", "Rear side, near Block D; deliveries and staff"),
    ]:
        gate = Gate(society_id=society.id, name=gate_name, location=location)
        db.add(gate)
        summary.gates += 1
        for direction in (LaneDirection.ENTRY, LaneDirection.EXIT):
            key = generate_device_key()
            device_name = f"{gate_name} - {direction.value} camera"
            device = Device(
                gate=gate,
                name=device_name,
                direction=direction,
                api_key_hash=key.hash,
                api_key_prefix=key.prefix,
            )
            db.add(device)
            lanes.setdefault(gate_name, {})[direction] = device
            summary.devices += 1
            summary.device_keys[device_name] = key.plaintext

    for plate, reason in WATCHLIST:
        db.add(WatchlistEntry(society_id=society.id, plate_normalized=plate, reason=reason))
        summary.watchlist += 1

    if history_days:
        await db.flush()  # assign ids

        def make_plate(*, two_wheeler: bool) -> str:
            while True:
                kind = VehicleType.TWO_WHEELER if two_wheeler else VehicleType.CAR
                plate = normalize_typed_plate(_plate(rng, kind))
                if plate not in used_plates:
                    used_plates.add(plate)
                    return plate

        def gate_lanes(name: str) -> GateLanes:
            entry, exit_ = lanes[name][LaneDirection.ENTRY], lanes[name][LaneDirection.EXIT]
            return GateLanes(
                entry=Lane(entry.gate_id, entry.id), exit=Lane(exit_.gate_id, exit_.id)
            )

        history = await add_history(
            db,
            society_id=society.id,
            rng=rng,
            now=now or datetime.now(UTC),
            days=history_days,
            limits=society_settings.defaults(settings),
            flats=[
                FlatContacts(flat.id, [u.id for u in residents_by_flat[i]])
                for i, flat in enumerate(flats)
            ],
            guard_ids=[guard.id for guard in guards],
            residents_cars=[
                ResidentCar(v.id, v.plate_normalized, v.plate_normalized) for v in vehicles
            ],
            main_gate=gate_lanes("Main Gate"),
            service_gate=gate_lanes("Service Gate"),
            make_plate=make_plate,
            live=live,
            focus_flat=next(
                FlatContacts(flat.id, [u.id for u in residents_by_flat[i]])
                for i, flat in enumerate(flats)
                if (flat.block, flat.number) == DEMO_RESIDENT_FLAT
            ),
        )
        summary.history_visits = history.visits
        summary.history_gate_events = history.gate_events

    await db.commit()
    return summary


HISTORY_DAYS = 14


async def _main(reset: bool, history_days: int) -> None:
    settings = get_settings()
    async with SessionLocal() as db:
        if reset:
            if settings.app_env == "production":
                raise SystemExit("Refusing to --reset a production database.")
            await reset_database(db)
            print("All tables emptied.")
        elif await is_seeded(db):
            print("Database already has data; nothing to do. Use --reset to start over.")
            return
        summary = await seed(db, settings, history_days=history_days, live=history_days > 0)
    await engine.dispose()

    print(
        f"Seeded {summary.flats} flats, {summary.residents} residents, "
        f"{summary.vehicles} vehicles, {summary.guards} guards, {summary.gates} gates, "
        f"{summary.devices} devices, {summary.watchlist} watchlist entries."
    )
    if history_days:
        print(
            f"Demo history: {summary.history_visits} past visits and "
            f"{summary.history_gate_events} gate reads over {history_days} days (made-up data)."
        )
    print(f"\nDemo logins (password: {settings.demo_password})")
    for email in (DEMO_ADMIN_EMAIL, DEMO_GUARD_EMAIL, DEMO_RESIDENT_EMAIL):
        print(f"  {email}")
    print("\nDevice API keys (shown once; rotate them via POST /api/v1/devices/{id}/rotate-key):")
    for name, key in summary.device_keys.items():
        print(f"  {name}: {key}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed GateSense with demo data.")
    parser.add_argument("--reset", action="store_true", help="empty every table first")
    parser.add_argument(
        "--no-history",
        action="store_true",
        help=f"skip the {HISTORY_DAYS} days of made-up past visits for the dashboard",
    )
    args = parser.parse_args()
    event_loop.run(_main(args.reset, 0 if args.no_history else HISTORY_DAYS))


if __name__ == "__main__":
    main()
