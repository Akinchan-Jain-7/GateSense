from datetime import timedelta

import cv2
import numpy as np
import pytest

from gatesense_anpr.models import Image
from gatesense_anpr.normaliser import clean, edit_distance, looks_like_plate
from gatesense_anpr.tracker import PlateTracker, encode_snapshot
from tests.conftest import T0


def at(seconds: float) -> object:
    return T0 + timedelta(seconds=seconds)


def test_agreeing_reads_are_sent_once_early(frame_image: Image) -> None:
    tracker = PlateTracker(gap_seconds=2, min_agreeing_reads=3)
    sent = []
    for i, (text, conf) in enumerate(
        [
            ("DL01AB1234", 0.9),
            ("DL01AB1Z34", 0.5),
            ("DL01AB1234", 0.8),
            ("DL01AB1234", 0.85),
            ("DL01AB1234", 0.9),
        ]  # fmt: skip
    ):
        sent += tracker.add(text, conf, T0 + timedelta(seconds=i * 0.2), frame_image)

    assert len(sent) == 1  # the 5th read doesn't send again
    read = sent[0]
    assert read.plate_text == "DL01AB1234"
    assert read.votes == 3
    assert read.confidence == pytest.approx((0.9 + 0.8 + 0.85) / 3, abs=1e-4)
    assert read.captured_at == T0
    assert read.raw_texts == ("DL01AB1234", "DL01AB1Z34")
    assert read.snapshot_jpeg and read.snapshot_jpeg[:3] == b"\xff\xd8\xff"
    assert tracker.expire(T0 + timedelta(seconds=10)) == []  # already sent


def test_a_short_sighting_is_sent_when_the_car_is_gone(frame_image: Image) -> None:
    tracker = PlateTracker(gap_seconds=2, min_agreeing_reads=3)
    assert tracker.add("UP16Z5678", 0.7, T0, frame_image) == []
    assert tracker.add("UP16Z5G78", 0.9, T0 + timedelta(seconds=0.3), frame_image) == []
    assert tracker.expire(T0 + timedelta(seconds=1)) == []  # not gone long enough
    (read,) = tracker.expire(T0 + timedelta(seconds=2.3))
    assert read.plate_text == "UP16Z5G78"  # higher total confidence wins the vote
    assert read.votes == 1


def test_different_plates_get_different_tracks(frame_image: Image) -> None:
    tracker = PlateTracker(gap_seconds=2, min_agreeing_reads=2)
    sent = []
    for text in ["DL01AB1234", "HR26DK8337", "DL01AB1234", "HR26DK8337"]:
        sent += tracker.add(text, 0.9, T0, frame_image)
    assert sorted(r.plate_text for r in sent) == ["DL01AB1234", "HR26DK8337"]


def test_same_plate_after_a_gap_is_a_new_sighting(frame_image: Image) -> None:
    tracker = PlateTracker(gap_seconds=2, min_agreeing_reads=1)
    first = tracker.add("KA05MN0042", 0.9, T0, frame_image)
    later = tracker.add("KA05MN0042", 0.9, T0 + timedelta(seconds=30), frame_image)
    assert len(first) == 1
    assert len(later) == 1


def test_flush_sends_everything_pending(frame_image: Image) -> None:
    tracker = PlateTracker(gap_seconds=2, min_agreeing_reads=5)
    tracker.add("DL01AB1234", 0.9, T0, frame_image)
    tracker.add("MH12DE1433", 0.9, T0, frame_image)
    assert {r.plate_text for r in tracker.flush()} == {"DL01AB1234", "MH12DE1433"}
    assert tracker.flush() == []


def test_snapshots_are_downscaled_jpegs() -> None:
    big = np.zeros((1080, 1920, 3), dtype=np.uint8)
    decoded = cv2.imdecode(np.frombuffer(encode_snapshot(big), np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    assert decoded.shape == (720, 1280, 3)


@pytest.mark.parametrize(
    ("text", "cleaned", "plausible"),
    [
        ("dl 01-ab 1234", "DL01AB1234", True),
        ("IND DL01AB1234", "INDDL01AB1234", True),
        ("RJ14C1", "RJ14C1", True),
        ("TAXI", "TAXI", False),  # no digits
        ("123456", "123456", False),  # no letters
        ("A1", "A1", False),  # too short
        ("DL01AB1234DL01AB", "DL01AB1234DL01AB", False),  # too long
    ],
)
def test_clean_and_junk_filter(text: str, cleaned: str, plausible: bool) -> None:
    assert clean(text) == cleaned
    assert looks_like_plate(cleaned) is plausible


def test_edit_distance() -> None:
    assert edit_distance("DL01AB1234", "DL01AB1234") == 0
    assert edit_distance("DL01AB1234", "DL01AB1Z34") == 1
    assert edit_distance("DL01AB1234", "DL01AB123") == 1
    assert edit_distance("", "ABC") == 3
