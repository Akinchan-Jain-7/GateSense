"""Run the demo traffic simulator.

    gatesense-sim --api http://127.0.0.1:8000 --speed 1

Settings can also come from the environment: SIM_API_URL, SIM_PASSWORD (the demo
password), SIM_ADMIN_EMAIL, SIM_GUARD_EMAIL, SIM_SPEED, SIM_TICK_SECONDS,
SIM_LEAVE_DEVICES.
"""

import argparse
import logging
import os
import random
import time

import httpx

from gatesense_sim.api import Api, NeedsBootstrapError
from gatesense_sim.world import World

logger = logging.getLogger("gatesense_sim")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    env = os.environ.get
    parser = argparse.ArgumentParser(description="GateSense demo traffic simulator")
    parser.add_argument("--api", default=env("SIM_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--password", default=env("SIM_PASSWORD", "GateSense@123"))
    parser.add_argument("--admin", default=env("SIM_ADMIN_EMAIL", "admin@example.com"))
    parser.add_argument("--guard", default=env("SIM_GUARD_EMAIL", "guard@example.com"))
    parser.add_argument(
        "--speed",
        type=float,
        default=float(env("SIM_SPEED", "1")),
        help="time compression: 2 = twice as busy, visits twice as short",
    )
    parser.add_argument("--tick", type=float, default=float(env("SIM_TICK_SECONDS", "5")))
    parser.add_argument("--seed", type=int, help="random seed (repeatable runs)")
    parser.add_argument("--minutes", type=float, help="stop after this many minutes")
    parser.add_argument(
        "--leave-devices",
        default=env("SIM_LEAVE_DEVICES", "Laptop webcam"),
        help="comma-separated camera name prefixes the simulator must not use (real cameras)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    api = Api(args.api, args.password)
    world = World(
        api,
        admin_email=args.admin,
        guard_email=args.guard,
        speed=args.speed,
        rng=random.Random(args.seed),  # noqa: S311 - demo traffic
        leave_devices=tuple(p.strip() for p in args.leave_devices.split(",") if p.strip()),
    )
    deadline = time.monotonic() + args.minutes * 60 if args.minutes else None
    bootstrapped = False
    wait = 5.0
    while deadline is None or time.monotonic() < deadline:
        try:
            if not bootstrapped:
                world.bootstrap()
                bootstrapped, wait = True, 5.0
            world.run_due()
            world.tick(args.tick)
        except NeedsBootstrapError as error:
            logger.warning("starting over: %s", error)  # e.g. the demo was just reset
            bootstrapped = False
        except httpx.TransportError as error:
            logger.warning("API unreachable (%s); retrying in %.0fs", error, wait)
            bootstrapped = False
            time.sleep(wait)
            wait = min(wait * 2, 120)
            continue
        time.sleep(args.tick)
    api.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
