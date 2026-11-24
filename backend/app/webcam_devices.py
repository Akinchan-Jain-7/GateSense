"""Set up a laptop webcam as a GateSense camera, for demos on your own machine.

    cd backend
    uv run python -m app.webcam_devices          # after: uv run python -m app.seed

What it does:
1. Makes sure the society's gate (default "Main Gate") has two cameras named
   "Laptop webcam - entry" and "Laptop webcam - exit". One webcam plays both: the live
   preview (`gatesense-anpr --source 0 --preview`) switches lanes, and each lane sends with
   its own device key because the server knows a lane by its device.
2. Gives both a fresh API key. Keys are stored hashed, so the only way to hand one out
   again is a new one; the old key stops working at once.
3. Writes the two keys into `anpr/.env` (ANPR_DEVICE_KEY, ANPR_EXIT_DEVICE_KEY), keeping
   every other line of that file, so the camera program picks them up by itself.
4. Prints plates to hold up to the camera, and writes `anpr/data/demo-plates.html`: a page
   of them to show on your phone or print. A resident's car, a watchlist plate and a new car.

Run it again after `python -m app.seed --reset` or a demo reset (both replace devices).
Each run is written to the audit log, like a key rotation in the admin screens.
"""

import argparse
import html
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import event_loop
from app.core.security import generate_device_key
from app.db.session import SessionLocal, engine
from app.models import AuditLog, Device, Flat, Gate, Society, Vehicle, WatchlistEntry
from app.models.enums import LaneDirection
from app.services.plates import is_valid_plate

REPO_DIR = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = REPO_DIR / "anpr" / ".env"
DEFAULT_PLATES_PAGE = REPO_DIR / "anpr" / "data" / "demo-plates.html"
DEVICE_NAMES = {
    LaneDirection.ENTRY: "Laptop webcam - entry",
    LaneDirection.EXIT: "Laptop webcam - exit",
}
ENV_KEYS = {LaneDirection.ENTRY: "ANPR_DEVICE_KEY", LaneDirection.EXIT: "ANPR_EXIT_DEVICE_KEY"}
# Plates for "a car nobody knows". Valid Indian plates; checked against the database.
NEW_CAR_CANDIDATES = ["KA05MN4821", "MH12QX7305", "TN09BZ6618", "GJ01RK2290", "RJ14CW5137"]
# Prefer the demo resident's flat (resident@example.com) so their app gets the approval.
DEMO_RESIDENT_FLAT = ("B", "402")


class SetupError(Exception):
    pass


@dataclass
class DemoPlate:
    plate: str
    what: str  # "Resident car, flat B-402"
    expect: str  # what should happen at the gate


@dataclass
class WebcamSetup:
    gate: str
    keys: dict[LaneDirection, str]
    created: list[str] = field(default_factory=list)
    plates: list[DemoPlate] = field(default_factory=list)
    demo_flat: str | None = None


async def setup_webcam(
    db: AsyncSession, *, gate_name: str = "Main Gate", society_name: str | None = None
) -> WebcamSetup:
    society = await _society(db, society_name)
    gate = await db.scalar(
        select(Gate).where(Gate.society_id == society.id, Gate.name == gate_name)
    )
    if gate is None:
        names = (await db.scalars(select(Gate.name).where(Gate.society_id == society.id))).all()
        raise SetupError(f"No gate called {gate_name!r}. Gates: {', '.join(names) or 'none'}.")

    result = WebcamSetup(gate=gate.name, keys={})
    for direction, name in DEVICE_NAMES.items():
        device = await db.scalar(
            select(Device).where(Device.gate_id == gate.id, Device.name == name)
        )
        key = generate_device_key()
        if device is None:
            device = Device(
                gate_id=gate.id,
                name=name,
                direction=direction,
                api_key_hash=key.hash,
                api_key_prefix=key.prefix,
            )
            db.add(device)
            await db.flush()
            result.created.append(name)
            action = "device.create"
        else:
            device.api_key_hash, device.api_key_prefix = key.hash, key.prefix
            device.direction, device.is_active = direction, True
            action = "device.rotate_key"
        db.add(
            AuditLog(
                society_id=society.id,
                actor_id=None,  # a command run on the server, not a signed-in admin
                action=action,
                entity_type="device",
                entity_id=device.id,
                changes={"new_prefix": key.prefix, "via": "python -m app.webcam_devices"},
            )
        )
        result.keys[direction] = key.plaintext

    result.plates, result.demo_flat = await _demo_plates(db, society.id)
    await db.commit()
    return result


async def _society(db: AsyncSession, name: str | None) -> Society:
    societies = (await db.scalars(select(Society).order_by(Society.created_at))).all()
    if name is not None:
        societies = [s for s in societies if s.name == name]
    if not societies:
        raise SetupError("No society found. Run `uv run python -m app.seed` first.")
    if len(societies) > 1:
        raise SetupError("More than one society; pick one with --society.")
    return societies[0]


async def _demo_plates(
    db: AsyncSession, society_id: uuid.UUID
) -> tuple[list[DemoPlate], str | None]:
    vehicles = (
        await db.scalars(
            select(Vehicle)
            .options(selectinload(Vehicle.flat))
            .where(Vehicle.society_id == society_id, Vehicle.is_active)
            .order_by(Vehicle.created_at, Vehicle.plate_normalized)
        )
    ).all()
    cars = [v for v in vehicles if v.vehicle_type.value == "car"] or list(vehicles)
    demo_flat = await db.scalar(
        select(Flat).where(
            Flat.society_id == society_id,
            Flat.block == DEMO_RESIDENT_FLAT[0],
            Flat.number == DEMO_RESIDENT_FLAT[1],
        )
    )
    cars.sort(key=lambda v: demo_flat is None or v.flat_id != demo_flat.id)  # theirs first

    plates = [
        DemoPlate(
            v.plate_normalized,
            f"Resident car, flat {v.flat.label}",
            "Entry is logged by itself (green). Show it again in Exit mode to close it.",
        )
        for v in cars[:2]
    ]
    known = {v.plate_normalized for v in vehicles}
    watch = await db.scalar(
        select(WatchlistEntry.plate_normalized)
        .where(WatchlistEntry.society_id == society_id)
        .order_by(WatchlistEntry.plate_normalized)
    )
    if watch:
        known.add(watch)
        plates.append(DemoPlate(watch, "On the watchlist", "Red alert on the guard console."))
    new_car = next((p for p in NEW_CAR_CANDIDATES if p not in known and is_valid_plate(p)), None)
    if new_car:
        plates.append(
            DemoPlate(
                new_car,
                "A car nobody knows",
                "Amber: register the visitor (name, phone, email, flat) on the guard console.",
            )
        )
    return plates, demo_flat.label if demo_flat else None


def write_env(path: Path, values: dict[str, str]) -> None:
    """Set `values` in a .env file: replace those lines if present, append them if not,
    leave every other line exactly as it was."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(values)
    out: list[str] = []
    for line in lines:
        name = line.split("=", 1)[0].strip().removeprefix("export ").strip()
        if name in remaining and not line.lstrip().startswith("#"):
            out.append(f"{name}={remaining.pop(name)}")
        else:
            out.append(line)
    if remaining and out and out[-1].strip():
        out.append("")
    if remaining:
        out.append("# Laptop webcam devices (python -m app.webcam_devices)")
    out += [f"{name}={value}" for name, value in remaining.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def format_plate(plate: str) -> str:
    """UP16AB1234 -> UP16 AB 1234; 22BH1234AA -> 22 BH 1234 AA (as printed on plates)."""
    if len(plate) >= 9 and plate[2:4] == "BH":
        return f"{plate[:2]} BH {plate[4:8]} {plate[8:]}"
    head = plate[:4] if plate[3].isdigit() else plate[:3]
    rest = plate[len(head) :]
    letters = rest.rstrip("0123456789")
    return " ".join(part for part in (head, letters, rest[len(letters) :]) if part)


def plates_page(plates: list[DemoPlate]) -> str:
    """A page of big plates to show the camera on a phone or print (one per screen)."""
    cards = "\n".join(
        "  <section>\n"
        '    <div class="plate"><span class="ind">IND</span>'
        f'<span class="num">{html.escape(format_plate(p.plate))}</span></div>\n'
        f"    <p><strong>{html.escape(p.what)}</strong><br />{html.escape(p.expect)}</p>\n"
        "  </section>"
        for p in plates
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>GateSense demo plates</title>
<style>
  body {{ margin: 0; font: 16px/1.5 'Segoe UI', system-ui, sans-serif; background: #f7f8fa;
    color: #15181d; }}
  section {{ min-height: 100vh; display: grid; place-content: center; gap: 24px; padding: 24px;
    text-align: center; break-after: page; }}
  .plate {{ display: inline-flex; align-items: stretch; margin: 0 auto; border: 6px solid #111;
    border-radius: 14px; background: #fff; overflow: hidden; }}
  .ind {{ display: grid; place-items: end center; width: 56px; padding-bottom: 10px;
    background: #2147c9; color: #fff; font: 700 16px/1 Arial, sans-serif; }}
  .num {{ padding: 18px 28px; font: 700 min(12vw, 96px)/1 'Arial Narrow', Arial, sans-serif;
    letter-spacing: 0.06em; white-space: nowrap; }}
  p {{ margin: 0; color: #5b6470; }}
  p strong {{ color: #15181d; }}
</style>
</head>
<body>
{cards}
</body>
</html>
"""


async def _main(args: argparse.Namespace) -> WebcamSetup:
    try:
        async with SessionLocal() as db:
            return await setup_webcam(db, gate_name=args.gate, society_name=args.society)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Set up the laptop webcam as a camera.")
    parser.add_argument("--gate", default="Main Gate", help="gate to put the webcam on")
    parser.add_argument("--society", help="society name (only if there are several)")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--plates-page", type=Path, default=DEFAULT_PLATES_PAGE)
    parser.add_argument(
        "--print-only", action="store_true", help="print the keys; don't write any file"
    )
    args = parser.parse_args(argv)
    try:
        result = event_loop.run(_main(args))
    except SetupError as error:
        print(f"Not set up: {error}")
        return 1

    values = {ENV_KEYS[d]: key for d, key in result.keys.items()}
    print(f"Laptop webcam cameras on {result.gate}: entry and exit (fresh keys).")
    if args.print_only:
        for name, value in values.items():
            print(f"  {name}={value}")
    else:
        write_env(args.env_file, values)
        args.plates_page.parent.mkdir(parents=True, exist_ok=True)
        args.plates_page.write_text(plates_page(result.plates), encoding="utf-8")
        print(f"Keys written to {args.env_file}")
        print(f"Plates to show the camera: {args.plates_page}")
    print("\nPlates to try:")
    for p in result.plates:
        print(f"  {format_plate(p.plate):<15} {p.what}: {p.expect}")
    if result.demo_flat:
        print(
            f"\nFor a new car, register the visit to flat {result.demo_flat}: the demo "
            "resident (resident@example.com) gets the approval."
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
