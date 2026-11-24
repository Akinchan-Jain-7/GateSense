"""Synthetic webcam benchmark: how well do crop + OCR + voting read plates held up to a
laptop camera?

    uv run python eval/webcam_benchmark.py                  # all reading settings
    uv run python eval/webcam_benchmark.py --plates 8 --frames 4 --configs baseline

Real labelled webcam photos are better (anpr/DATASET.md, the preview's "Save for
testing"), but they take time to collect. This bench renders Indian plates into 1280x720
frames with the problems a webcam demo has, and compares *reading settings* on exactly
the same frames:

    clear    plate held steady, good light
    small    plate far from the camera (about 130 px wide)
    blurry   out of focus + a little hand shake
    tilted   held at an angle (perspective)
    dim      a dark room: low brightness, more sensor noise
    glare    a bright reflection across part of the plate
    phone    a plate shown on a phone screen: bluish, lower contrast, pixel grid

Each "car" is several frames with small hand movements, and the detector's box is
simulated around the true plate with random slack (YOLO boxes are rarely exact), so
cropping matters. Only OCR is real (EasyOCR); the detector is not part of this bench.

Three numbers per condition:
- frame: one frame's read is exactly right;
- car: the tracker's voted read for the car is exactly right (what gets sent);
- car after repair: the server's plate repair (backend/app/services/plates.py) turns the
  car's read into the right plate. This is what the guard console finally shows.

Synthetic text is not a real plate font, so absolute numbers are optimistic. Use the bench
to compare settings, and the labelled photos for the real accuracy.

Writes eval/results/webcam_benchmark.md and .json.
"""

import argparse
import importlib
import json
import random
import statistics
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import numpy.typing as npt

from gatesense_anpr.detector import crop
from gatesense_anpr.metrics import char_accuracy, markdown_table
from gatesense_anpr.models import Box, Image
from gatesense_anpr.normaliser import clean, looks_like_plate
from gatesense_anpr.ocr import OcrEngine, build_engine, prepare_crop
from gatesense_anpr.tracker import PlateTracker, Voting

RESULTS = Path(__file__).resolve().parent / "results"
BACKEND = Path(__file__).resolve().parents[2] / "backend"
CONDITIONS = ("clear", "small", "blurry", "tilted", "dim", "glare", "phone")
WIDTH, HEIGHT = 1280, 720
STATES = ("DL", "UP", "HR", "MH", "KA", "RJ", "GJ", "TN", "PB", "MP", "WB", "TS")
LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"  # no I or O: they aren't issued in series letters


def server_repair() -> Callable[[str], str | None]:
    """The backend's plate repair, if the backend folder is next to anpr/."""
    sys.path.insert(0, str(BACKEND))
    try:
        plates = importlib.import_module("app.services.plates")
    except ImportError:  # only when anpr/ is used without the backend next to it
        return lambda text: None
    finally:
        sys.path.remove(str(BACKEND))

    def repair(text: str) -> str | None:
        reading = plates.read_ocr_plate(text)
        return str(reading.plate) if reading else None

    return repair


def make_plates(count: int, rng: random.Random) -> list[str]:
    plates: set[str] = set()
    while len(plates) < count:
        if rng.random() < 0.15:  # Bharat series: 22 BH 1234 AA
            plate = f"{rng.randint(21, 25)}BH{rng.randint(0, 9999):04d}{rng.choice(LETTERS)}"
            plate += rng.choice(LETTERS)
        else:
            series = "".join(rng.choice(LETTERS) for _ in range(rng.choice((1, 2, 2, 2))))
            plate = (
                f"{rng.choice(STATES)}{rng.randint(1, 99):02d}{series}{rng.randint(1, 9999):04d}"
            )
        plates.add(plate)
    return sorted(plates)


def render_plate(text: str) -> Image:
    """A flat plate image: white, black border, blue IND strip, text grouped like a real plate."""
    height, width = 110, 520
    plate = np.full((height, width, 3), 245, dtype=np.uint8)
    cv2.rectangle(plate, (0, 0), (width - 1, height - 1), (20, 20, 20), 6)
    cv2.rectangle(plate, (6, 6), (40, height - 7), (201, 71, 33), -1)  # BGR blue strip
    cv2.putText(plate, "IND", (9, height - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1)
    shown = group(text)
    font, thickness = cv2.FONT_HERSHEY_DUPLEX, 5
    scale = 2.2
    (tw, th), _ = cv2.getTextSize(shown, font, scale, thickness)
    scale *= min(1.0, (width - 70) / tw)
    (tw, th), _ = cv2.getTextSize(shown, font, scale, thickness)
    x = 46 + (width - 52 - tw) // 2
    y = (height + th) // 2
    cv2.putText(plate, shown, (x, y), font, scale, (15, 15, 15), thickness, cv2.LINE_AA)
    return plate


def group(plate: str) -> str:
    if plate[2:4] == "BH":
        return f"{plate[:2]} BH {plate[4:8]} {plate[8:]}"
    letters = plate[4:].rstrip("0123456789")
    return " ".join(p for p in (plate[:4], letters, plate[4 + len(letters) :]) if p)


@dataclass(frozen=True)
class Shot:
    image: Image
    corners: np.ndarray  # 4 x 2, plate corners in frame pixels


def background(rng: random.Random) -> Image:
    """A car-ish scene: a vertical gradient, a darker 'bumper' band and sensor noise."""
    top, bottom = rng.randint(60, 140), rng.randint(20, 90)
    column = np.linspace(top, bottom, HEIGHT, dtype=np.float32)[:, None]
    tint = np.array([rng.uniform(0.8, 1.2) for _ in range(3)], dtype=np.float32)
    scene = np.repeat(column, WIDTH, axis=1)[:, :, None] * tint
    band = rng.randint(HEIGHT // 2, HEIGHT - 120)
    scene[band : band + 160] *= 0.6
    return np.asarray(np.clip(scene, 0, 255), dtype=np.uint8)


def place(plate: Image, scene: Image, condition: str, rng: random.Random, frame: int) -> Shot:
    """Warp the plate into the scene; the condition decides size and angle."""
    ph, pw = plate.shape[:2]
    width = {"small": rng.uniform(120, 150)}.get(condition, rng.uniform(300, 460))
    height = width * ph / pw
    cx = WIDTH / 2 + rng.uniform(-150, 150) + 6 * np.sin(frame)  # hand movement
    cy = HEIGHT / 2 + rng.uniform(-80, 80) + 4 * np.cos(frame)
    angle = np.deg2rad(rng.uniform(-4, 4))
    corners = np.array(
        [
            [-width / 2, -height / 2],
            [width / 2, -height / 2],
            [width / 2, height / 2],
            [-width / 2, height / 2],
        ],
        dtype=np.float32,
    )
    rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    corners = corners @ rotation.T.astype(np.float32)
    if condition == "tilted":  # one side further away: perspective
        squeeze = rng.uniform(0.18, 0.3) * height
        side = rng.choice((0, 1))
        if side == 0:
            corners[0, 1] += squeeze / 2
            corners[3, 1] -= squeeze / 2
        else:
            corners[1, 1] += squeeze / 2
            corners[2, 1] -= squeeze / 2
        corners[:, 0] *= rng.uniform(0.8, 0.9)
    corners += np.array([cx, cy], dtype=np.float32)
    source = np.array([[0, 0], [pw, 0], [pw, ph], [0, ph]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(source, corners)
    warped = cv2.warpPerspective(plate, matrix, (WIDTH, HEIGHT))
    mask = cv2.warpPerspective(np.full((ph, pw), 255, np.uint8), matrix, (WIDTH, HEIGHT))
    image = scene.copy()
    image[mask > 0] = warped[mask > 0]
    return Shot(image=image, corners=corners)


def degrade(image: Image, condition: str, corners: np.ndarray, rng: random.Random) -> Image:
    out: npt.NDArray[Any] = image.astype(np.float32)
    noise = 4.0
    if condition == "blurry":
        k = rng.choice((5, 7, 9))
        out = cv2.GaussianBlur(out, (k, k), 0)
        motion = np.zeros((7, 7), np.float32)
        motion[3, :] = 1 / 7
        out = cv2.filter2D(out, -1, motion)
    elif condition == "dim":
        out = 255 * (out / 255) ** rng.uniform(1.8, 2.4) * rng.uniform(0.45, 0.6)
        noise = 9.0
    elif condition == "glare":
        x1, y1 = corners.min(axis=0)
        x2, y2 = corners.max(axis=0)
        centre = (int(rng.uniform(x1, x2)), int(rng.uniform(y1, y2)))
        axes = (int((x2 - x1) * rng.uniform(0.12, 0.22)), int((y2 - y1) * rng.uniform(0.6, 1.0)))
        glow: npt.NDArray[Any] = np.zeros(image.shape[:2], np.float32)
        cv2.ellipse(glow, centre, axes, rng.uniform(0, 180), 0, 360, 1.0, -1)
        glow = cv2.GaussianBlur(glow, (0, 0), max(axes) / 3)[:, :, None]
        out = out + glow * 255 * rng.uniform(0.75, 0.95)
    elif condition == "phone":  # a screen: bluish, washed out, visible pixel grid
        out = out * 0.8 + 35
        out[:, :, 0] *= 1.12  # more blue (BGR)
        out[:, :, 2] *= 0.92
        out[::3, :, :] *= 0.86
        out = cv2.GaussianBlur(out, (3, 3), 0)
    elif condition == "small":
        out = cv2.GaussianBlur(out, (3, 3), 0)
    out += np.random.default_rng(rng.randint(0, 2**31)).normal(0, noise, out.shape)
    out = np.clip(out, 0, 255).astype(np.uint8)
    ok, jpeg = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 70])  # webcam compression
    assert ok  # noqa: S101 - encoding a valid array can't fail
    return np.asarray(cv2.imdecode(jpeg, cv2.IMREAD_COLOR), dtype=np.uint8)


def detector_box(corners: np.ndarray, rng: random.Random) -> Box:
    """The true box, with each side moved in or out by up to 8% (like a real detector)."""
    x1, y1 = corners.min(axis=0)
    x2, y2 = corners.max(axis=0)
    w, h = x2 - x1, y2 - y1
    return Box(
        float(x1 + w * rng.uniform(-0.08, 0.05)),
        float(y1 + h * rng.uniform(-0.08, 0.08)),
        float(x2 + w * rng.uniform(-0.05, 0.08)),
        float(y2 + h * rng.uniform(-0.08, 0.08)),
    )


@dataclass(frozen=True)
class Car:
    plate: str
    condition: str
    frames: list[tuple[Image, Box]]


def make_cars(plates: list[str], frames: int, seed: int) -> list[Car]:
    cars = []
    for condition in CONDITIONS:
        for plate in plates:
            rng = random.Random(f"{seed}:{condition}:{plate}")  # noqa: S311 - test data
            flat, scene = render_plate(plate), background(rng)
            shots = []
            for i in range(frames):
                steady = random.Random(f"{seed}:{plate}:{condition}")  # noqa: S311 - test data
                shot = place(flat, scene, condition, steady, i)
                image = degrade(shot.image, condition, shot.corners, rng)
                shots.append((image, detector_box(shot.corners, rng)))
            cars.append(Car(plate, condition, shots))
    return cars


# --- reading settings to compare -------------------------------------------------------


@dataclass(frozen=True)
class Config:
    name: str
    description: str
    margin: float = 0.05  # crop margin around the detector's box
    target_height: int = 64  # upscale crops shorter than this
    enhance: bool = False  # grayscale + CLAHE contrast before OCR
    voting: Voting = "string"  # "string": whole-text votes; "chars": per-position votes


CONFIGS = {
    c.name: c
    for c in (
        Config("baseline", "Before: 5% margin, upscale to 64 px, whole-string votes"),
        Config("margin", "+ 12% margin around the box", margin=0.12),
        Config("upscale", "+ upscale to 96 px", margin=0.12, target_height=96),
        Config("contrast", "+ grey and CLAHE contrast", margin=0.12, target_height=96,
               enhance=True),
        Config(
            "chars", "+ per-character voting across frames", margin=0.12, target_height=96,
            enhance=True, voting="chars",
        ),
        Config("chars-no-contrast", "margin + upscale + per-character voting", margin=0.12,
               target_height=96, voting="chars"),
    )
}  # fmt: skip


def read(ocr: OcrEngine, image: Image, box: Box, config: Config) -> tuple[str, float]:
    from gatesense_anpr.ocr import enhance_contrast

    plate = crop(image, box, margin=config.margin)
    plate = prepare_crop(plate, target_height=config.target_height)
    if config.enhance:
        plate = enhance_contrast(plate)
    result = ocr.read(plate)
    if result is None:
        return "", 0.0
    return clean(result.text), result.confidence


def vote(reads: list[tuple[str, float]], config: Config) -> str:
    tracker = PlateTracker(min_agreeing_reads=3, voting=config.voting)
    start = datetime(2026, 11, 24, tzinfo=UTC)
    sent = []
    for i, (text, confidence) in enumerate(reads):
        if looks_like_plate(text):
            at = start + timedelta(seconds=0.2 * i)
            sent += tracker.add(text, confidence, at, np.zeros((2, 2, 3), np.uint8))
    sent += tracker.flush()
    return sent[0].plate_text if sent else ""


def run(cars: list[Car], ocr: OcrEngine, configs: list[Config]) -> dict[str, Any]:
    repair = server_repair()
    results: dict[str, Any] = {}
    for config in configs:
        rows: dict[str, dict[str, list[float]]] = {}
        started = time.perf_counter()
        calls = 0
        for car in cars:
            reads = [read(ocr, image, box, config) for image, box in car.frames]
            calls += len(reads)
            voted = vote(reads, config)
            for condition in (car.condition, "all"):
                row = rows.setdefault(
                    condition, {k: [] for k in ("frame", "car", "repaired", "chars")}
                )
                row["frame"] += [float(text == car.plate) for text, _ in reads]
                row["car"].append(float(voted == car.plate))
                row["repaired"].append(float(repair(voted) == car.plate) if voted else 0.0)
                row["chars"].append(char_accuracy(voted, car.plate))
        ms_per_read = (time.perf_counter() - started) * 1000 / max(1, calls)
        results[config.name] = {
            "description": config.description,
            "ms_per_read": round(ms_per_read, 1),
            "conditions": {
                condition: {key: round(statistics.fmean(values), 4) for key, values in row.items()}
                for condition, row in rows.items()
            },
        }
        print(f"{config.name:<18} {results[config.name]['conditions']['all']}", flush=True)
    return results


def write(results: dict[str, Any], args: argparse.Namespace) -> None:
    RESULTS.mkdir(exist_ok=True)
    meta = {
        "plates": args.plates,
        "frames_per_car": args.frames,
        "cars": args.plates * len(CONDITIONS),
        "ocr": args.ocr,
        "seed": args.seed,
    }
    # Settings can be run one at a time (each takes minutes on a laptop CPU): keep the
    # results of earlier runs made with the same frames, and add the new ones.
    path = RESULTS / "webcam_benchmark.json"
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        if previous.get("meta") == meta:
            results = {**previous["results"], **results}
    results = {name: results[name] for name in CONFIGS if name in results}
    path.write_text(
        json.dumps({"meta": meta, "results": results}, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Synthetic webcam benchmark",
        "",
        f"`eval/webcam_benchmark.py`: {meta['cars']} cars ({args.plates} plates x "
        f"{len(CONDITIONS)} conditions), {args.frames} frames each, {args.ocr} on CPU, "
        f"seed {args.seed}. Rendered plates, not photos: compare settings here, and use "
        "labelled webcam photos for real accuracy (see the script's docstring).",
        "",
        "## Settings (all conditions)",
        "",
    ]
    rows = []
    for name, result in results.items():
        r = result
        all_ = r["conditions"]["all"]
        rows.append(
            (name, r["description"], all_["frame"], all_["car"], all_["repaired"], r["ms_per_read"])
        )
    lines.append(
        markdown_table(
            [
                "Setting",
                "What changes",
                "Frame exact",
                "Car exact",
                "Car after server repair",
                "ms / read",
            ],
            rows,
        )
    )
    for name, result in results.items():
        r = result
        lines += ["", f"## `{name}` per condition", ""]
        lines.append(
            markdown_table(
                [
                    "Condition",
                    "Frame exact",
                    "Car exact",
                    "Car after server repair",
                    "Character accuracy",
                ],
                [
                    (c, v["frame"], v["car"], v["repaired"], v["chars"])
                    for c, v in r["conditions"].items()
                ],
            )
        )
    (RESULTS / "webcam_benchmark.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--plates", type=int, default=20, help="plates per condition")
    parser.add_argument("--frames", type=int, default=6, help="frames per car")
    parser.add_argument("--ocr", default="easyocr", choices=["easyocr", "paddleocr"])
    parser.add_argument("--configs", default=",".join(CONFIGS), help="comma-separated")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--save-examples", type=Path, help="write one frame per condition here")
    args = parser.parse_args(argv)
    plates = make_plates(args.plates, random.Random(args.seed))  # noqa: S311 - test data
    cars = make_cars(plates, args.frames, args.seed)
    if args.save_examples:
        args.save_examples.mkdir(parents=True, exist_ok=True)
        for car in cars[:: args.plates]:
            cv2.imwrite(str(args.save_examples / f"{car.condition}.jpg"), car.frames[0][0])
    ocr = build_engine(args.ocr)
    results = run(cars, ocr, [CONFIGS[name] for name in args.configs.split(",")])
    write(results, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
