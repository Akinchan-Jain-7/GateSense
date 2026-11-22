"""Load test for gate-event ingestion (`POST /api/v1/gate-events`), the hot path: every
car at every camera ends up here.

Each simulated user is a camera sending plate reads as fast as the server answers. The
mix is realistic: mostly residents' cars (repeat plates, so debounce kicks in like at a
real gate), unknown cars, a few uncertain reads, and a small JPEG snapshot on most reads.

Setup (needs the API in a seeded database, see docs/performance.md):

    cd loadtests && uv sync
    uv run locust --headless -u 40 -r 10 -t 60s --host http://127.0.0.1:8000 \\
        --csv results/run --only-summary

At start it signs in as the demo admin, rotates the four cameras' keys and loads the
resident plates. Don't point it at a production database: it rotates camera keys.
"""

import os
import random
import string
import threading
from datetime import UTC, datetime
from typing import Any

import requests
from locust import HttpUser, between, events, task

ADMIN_EMAIL = os.environ.get("LOADTEST_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("LOADTEST_ADMIN_PASSWORD", "GateSense@123")
STATES = ["UP", "DL", "HR", "MH", "KA", "RJ", "PB", "TN"]

# A plausible camera JPEG payload (~18 KB). The server checks the magic bytes, not pixels.
SNAPSHOT = b"\xff\xd8\xff\xe0" + os.urandom(18_000)

setup_lock = threading.Lock()
device_keys: list[str] = []
resident_plates: list[str] = []


@events.test_start.add_listener
def prepare(environment: Any, **_: Any) -> None:
    host = environment.host.rstrip("/")
    token = requests.post(
        f"{host}/api/v1/auth/login",
        data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=10,
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    devices = requests.get(f"{host}/api/v1/devices?limit=100", headers=headers, timeout=10)
    for device in devices.json()["items"]:
        rotated = requests.post(
            f"{host}/api/v1/devices/{device['id']}/rotate-key", headers=headers, timeout=10
        )
        device_keys.append(rotated.json()["api_key"])
    offset = 0
    while True:
        page = requests.get(
            f"{host}/api/v1/vehicles?limit=100&offset={offset}", headers=headers, timeout=10
        ).json()
        resident_plates.extend(v["plate_normalized"] for v in page["items"])
        offset += 100
        if offset >= page["total"]:
            break


def unknown_plate() -> str:
    letters = "".join(random.choices("ABCDEFGHJKLMNPRSTUVWXYZ", k=2))  # noqa: S311
    return f"{random.choice(STATES)}{random.randint(1, 99):02d}{letters}{random.randint(1, 9999):04d}"  # noqa: S311


class Camera(HttpUser):
    # A real gate sees a car every few seconds; this is a stress test, so barely any pause.
    wait_time = between(0, 0.05)

    def on_start(self) -> None:
        self.key = random.choice(device_keys)  # noqa: S311

    @task
    def send_read(self) -> None:
        roll = random.random()  # noqa: S311
        if roll < 0.6:
            plate, confidence = random.choice(resident_plates), random.uniform(0.85, 0.99)  # noqa: S311
        elif roll < 0.9:
            plate, confidence = unknown_plate(), random.uniform(0.85, 0.99)  # noqa: S311
        else:
            plate = unknown_plate().replace("0", "O", 1)
            confidence = random.uniform(0.4, 0.75)  # noqa: S311
        data = {
            "plate_text": plate,
            "confidence": f"{confidence:.3f}",
            "captured_at": datetime.now(UTC).isoformat(),
        }
        files = {"snapshot": ("snap.jpg", SNAPSHOT, "image/jpeg")} if roll < 0.8 else None
        with self.client.post(
            "/api/v1/gate-events",
            data=data,
            files=files,
            headers={"X-Device-Key": self.key},
            name="POST /api/v1/gate-events",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201):
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}: {response.text[:120]}")


__all__ = ["Camera", "string"]
