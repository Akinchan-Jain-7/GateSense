"""`--simulate`: realistic plate reads without a camera or a model.

Useful for demos and for testing the API path. Each read picks a plate, sometimes adds
the look-alike mistakes real OCR makes (O for 0, B for 8…), picks a confidence, and
renders a simple plate image as the snapshot.
"""

import random
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta

import cv2
import numpy as np

from gatesense_anpr.models import Image, PlateRead
from gatesense_anpr.tracker import encode_snapshot

# A few valid plates; pass the society's real ones with --plates for matching demos.
DEFAULT_PLATES = (
    "DL01AB1234", "UP16Z5678", "HR26DK8337", "MH12DE1433", "KA05MN0042",
    "DL3CAS0042", "UP14FT4410", "22BH1234AA", "RJ14CV2201", "GJ01HK9090",
)  # fmt: skip

LOOK_ALIKES = {"0": "O", "1": "I", "8": "B", "5": "S", "2": "Z", "B": "8", "O": "0"}


def add_ocr_noise(plate: str, rng: random.Random, probability: float = 0.25) -> str:
    """With some probability, swap one character for its look-alike."""
    if rng.random() >= probability:
        return plate
    positions = [i for i, c in enumerate(plate) if c in LOOK_ALIKES]
    if not positions:
        return plate
    i = rng.choice(positions)
    return plate[:i] + LOOK_ALIKES[plate[i]] + plate[i + 1 :]


def render_plate(text: str) -> Image:
    """A white plate with black text on a grey background, like a cropped camera frame."""
    frame = np.full((360, 640, 3), 90, dtype=np.uint8)
    cv2.rectangle(frame, (120, 140), (520, 220), (245, 245, 245), thickness=-1)
    cv2.rectangle(frame, (120, 140), (520, 220), (20, 20, 20), thickness=3)
    cv2.putText(frame, text, (140, 198), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (15, 15, 15), 3)
    return frame


def simulated_reads(
    count: int,
    *,
    plates: Sequence[str] = DEFAULT_PLATES,
    interval_seconds: float = 2.0,
    seed: int | None = None,
    start: datetime | None = None,
) -> Iterator[PlateRead]:
    rng = random.Random(seed)  # noqa: S311 - demo data, not security
    start = start or datetime.now(UTC)
    for i in range(count):
        plate = rng.choice(plates)
        text = add_ocr_noise(plate, rng)
        # Mostly confident reads; about 1 in 8 below the server's review threshold.
        confidence = rng.uniform(0.45, 0.79) if rng.random() < 0.125 else rng.uniform(0.82, 0.99)
        yield PlateRead(
            plate_text=text,
            confidence=round(confidence, 3),
            captured_at=start + timedelta(seconds=i * interval_seconds),
            snapshot_jpeg=encode_snapshot(render_plate(plate)),
            raw_texts=(text,),
        )
