"""Optional reading settings (per-character voting, contrast) and the webcam benchmark."""

import argparse
import json
import random
import sys
from datetime import timedelta
from pathlib import Path

import cv2
import numpy as np
import pytest

from gatesense_anpr import cli
from gatesense_anpr.config import AnprSettings
from gatesense_anpr.models import Box, Frame, Image, OcrResult
from gatesense_anpr.ocr import enhance_contrast
from gatesense_anpr.pipeline import Pipeline
from gatesense_anpr.tracker import PlateTracker
from tests.conftest import T0, make_constant_onnx
from tests.test_pipeline_and_sources import FakeDetector

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
import webcam_benchmark as bench  # noqa: E402


def feed(tracker: PlateTracker, texts: list[str], image: Image) -> list[str]:
    sent = []
    for i, text in enumerate(texts):
        sent += tracker.add(text, 0.8, T0 + timedelta(seconds=i * 0.2), image)
    return [read.plate_text for read in sent]


# --- per-character voting ----------------------------------------------------------------


def test_per_character_voting_recovers_a_plate_no_frame_read_fully(frame_image: Image) -> None:
    misreads = ["DL01AB1Z34", "DL0IAB1234", "DL01A81234"]  # each wrong in a different place
    assert feed(PlateTracker(voting="chars"), misreads, frame_image) == ["DL01AB1234"]
    # Whole-string voting can only pick one of the wrong strings (and waits for the car to go).
    whole = PlateTracker(voting="string")
    assert feed(whole, misreads, frame_image) == []
    assert [r.plate_text for r in whole.flush()] != ["DL01AB1234"]


def test_per_character_voting_waits_for_a_clear_majority(frame_image: Image) -> None:
    tracker = PlateTracker(voting="chars", min_agreeing_reads=3)
    flicker = ["DL01AB1234", "DL01AB1Z34", "DL01AB1734"] * 3  # position 8: a 3-way split
    assert feed(tracker, flicker[:8], frame_image) == []
    # ... but a car standing there for 3x the usual reads is sent with the best guess.
    assert feed(tracker, flicker[8:], frame_image) == ["DL01AB1234"]


def test_per_character_voting_uses_the_most_likely_length(frame_image: Image) -> None:
    tracker = PlateTracker(voting="chars", min_agreeing_reads=3, gap_seconds=1)
    feed(tracker, ["DL01AB1234", "DL01AB234", "DL01AB1234"], frame_image)  # one dropped digit
    [read] = tracker.expire(T0 + timedelta(seconds=10))
    assert read.plate_text == "DL01AB1234"
    assert read.votes == 2
    assert read.raw_texts == ("DL01AB1234", "DL01AB234")


def test_per_character_voting_still_keeps_different_cars_apart(frame_image: Image) -> None:
    tracker = PlateTracker(voting="chars", min_agreeing_reads=2)
    sent = feed(tracker, ["DL01AB1234", "HR26DK8337", "DL01AB1234", "HR26DK8337"], frame_image)
    assert sent == ["DL01AB1234", "HR26DK8337"]


def test_per_character_voting_on_flush(frame_image: Image) -> None:
    tracker = PlateTracker(voting="chars")
    feed(tracker, ["UP16Z5678", "UP16Z5G78"], frame_image)
    assert [r.plate_text for r in tracker.flush()] == ["UP16Z5678"]


# --- contrast ----------------------------------------------------------------------------


def test_contrast_makes_a_grey_crop_with_more_contrast() -> None:
    rng = np.random.default_rng(0)
    flat = np.clip(rng.normal(120, 6, (40, 160, 3)), 0, 255).astype(np.uint8)
    flat[15:25, 20:140] = 105  # faint "text"
    boosted = enhance_contrast(flat)
    assert boosted.shape == flat.shape
    assert (boosted[:, :, 0] == boosted[:, :, 1]).all()
    assert boosted.std() > flat.std()
    empty = np.zeros((0, 0, 3), dtype=np.uint8)
    assert enhance_contrast(empty) is empty


class RecordingOcr:
    name = "recording"

    def __init__(self) -> None:
        self.seen: list[Image] = []

    def read(self, plate: Image) -> OcrResult | None:
        self.seen.append(plate)
        return OcrResult("DL01AB1234", 0.9)


def test_pipeline_applies_contrast_only_when_asked(frame_image: Image) -> None:
    colour = frame_image.copy()
    colour[:, :, 2] = 200  # not grey
    for contrast, grey in ((False, False), (True, True)):
        ocr = RecordingOcr()
        Pipeline(
            FakeDetector([Box(10, 10, 200, 60)]), ocr, PlateTracker(), contrast=contrast
        ).process(Frame(colour, T0))
        channels_equal = bool((ocr.seen[0][:, :, 0] == ocr.seen[0][:, :, 2]).all())
        assert channels_equal is grey


def test_settings_reach_the_pipeline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    model = make_constant_onnx(tmp_path / "m.onnx", np.zeros((1, 5, 10), dtype=np.float32))
    monkeypatch.setenv("ANPR_DETECTOR_MODEL", str(model))
    monkeypatch.setenv("ANPR_OCR_CONTRAST", "true")
    monkeypatch.setenv("ANPR_TRACK_VOTING", "chars")
    monkeypatch.setattr("gatesense_anpr.ocr.build_engine", lambda name: RecordingOcr())
    pipeline = cli.build_pipeline(AnprSettings())
    assert pipeline.contrast is True
    assert pipeline.tracker.voting == "chars"
    monkeypatch.delenv("ANPR_OCR_CONTRAST")
    monkeypatch.delenv("ANPR_TRACK_VOTING")
    defaults = AnprSettings(_env_file=None)  # type: ignore[call-arg]
    assert (defaults.ocr_contrast, defaults.track_voting) == (False, "string")


# --- the webcam benchmark ----------------------------------------------------------------


def test_bench_plates_are_valid_and_grouped_like_real_plates() -> None:
    plates = bench.make_plates(40, random.Random(1))
    assert len(set(plates)) == 40
    repair = bench.server_repair()
    assert all(repair(p) is not None for p in plates if not p.startswith("DL"))
    assert bench.group("UP16BK2834") == "UP16 BK 2834"
    assert bench.group("22BH3092JZ") == "22 BH 3092 JZ"
    assert bench.render_plate("UP16BK2834").shape == (110, 520, 3)


def test_bench_makes_every_condition(tmp_path: Path) -> None:
    cars = bench.make_cars(["UP16BK2834"], frames=2, seed=3)
    assert [c.condition for c in cars] == list(bench.CONDITIONS)
    for car in cars:
        image, box = car.frames[0]
        assert image.shape == (bench.HEIGHT, bench.WIDTH, 3)
        assert 0 <= box.x1 < box.x2 <= bench.WIDTH * 1.1


def test_bench_scores_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class PerfectOcr:
        name = "perfect"

        def __init__(self, text: str) -> None:
            self.text = text

        def read(self, plate: Image) -> OcrResult | None:
            return OcrResult(self.text, 0.9)

    cars = bench.make_cars(["UP16BK2834"], frames=3, seed=3)
    configs = [bench.CONFIGS["baseline"], bench.CONFIGS["chars"]]
    results = bench.run(cars, PerfectOcr("UP16BK2834"), configs)
    for name in ("baseline", "chars"):
        assert results[name]["conditions"]["all"] == {
            "frame": 1.0,
            "car": 1.0,
            "repaired": 1.0,
            "chars": 1.0,
        }
    # A look-alike slip is wrong for the camera but right after the server's repair.
    slip = bench.run(cars, PerfectOcr("UP16BK2B34"), configs[:1])["baseline"]["conditions"]["all"]
    assert (slip["car"], slip["repaired"]) == (0.0, 1.0)

    monkeypatch.setattr(bench, "RESULTS", tmp_path)
    args = argparse.Namespace(plates=1, frames=3, ocr="easyocr", seed=3)
    bench.write(results, args)
    bench.write({"upscale": results["baseline"]}, args)  # a later run adds a setting
    saved = json.loads((tmp_path / "webcam_benchmark.json").read_text())
    assert list(saved["results"]) == ["baseline", "upscale", "chars"]
    assert "## `chars` per condition" in (tmp_path / "webcam_benchmark.md").read_text()


def test_bench_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(bench, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(bench, "build_engine", lambda name: RecordingOcr())
    examples = tmp_path / "examples"
    code = bench.main(
        [
            "--plates",
            "1",
            "--frames",
            "1",
            "--configs",
            "contrast",
            "--save-examples",
            str(examples),
        ]
    )
    assert code == 0
    assert sorted(p.stem for p in examples.glob("*.jpg")) == sorted(bench.CONDITIONS)
    assert cv2.imread(str(examples / "glare.jpg")) is not None
    assert (tmp_path / "results" / "webcam_benchmark.md").exists()
