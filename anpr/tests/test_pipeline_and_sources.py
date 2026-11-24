from datetime import timedelta
from pathlib import Path

import cv2
import numpy as np
import pytest

from gatesense_anpr.models import Box, Detection, Frame, Image, OcrResult
from gatesense_anpr.ocr import join_lines, prepare_crop
from gatesense_anpr.pipeline import Pipeline
from gatesense_anpr.sources import image_folder, is_folder, is_live, open_source, video
from gatesense_anpr.tracker import PlateTracker
from tests.conftest import T0


class FakeDetector:
    def __init__(self, boxes: list[Box]) -> None:
        self.boxes = boxes

    def detect(self, image: Image) -> list[Detection]:
        return [Detection(box=b, score=0.9) for b in self.boxes]


class ScriptedOcr:
    """Returns the next scripted reading each call (None = OCR found nothing)."""

    name = "scripted"

    def __init__(self, texts: list[str | None]) -> None:
        self.texts = list(texts)

    def read(self, plate: Image) -> OcrResult | None:
        text = self.texts.pop(0)
        return OcrResult(text=text, confidence=0.9) if text is not None else None


def run(pipeline: Pipeline, frames: int, image: Image) -> list[str]:
    reads = []
    for i in range(frames):
        reads += pipeline.process(Frame(image=image, captured_at=T0 + timedelta(seconds=i * 0.2)))
    reads += pipeline.finish()
    return [r.plate_text for r in reads]


def test_pipeline_turns_frames_into_one_read_per_car(frame_image: Image) -> None:
    ocr = ScriptedOcr(["dl 01 ab 1234", "DL01AB1234", None, "STOP", "DL01AB1234"])
    pipeline = Pipeline(
        FakeDetector([Box(100, 100, 300, 160)]), ocr, PlateTracker(min_agreeing_reads=3)
    )
    assert run(pipeline, 5, frame_image) == ["DL01AB1234"]


def test_pipeline_with_no_plates_sends_nothing(frame_image: Image) -> None:
    pipeline = Pipeline(FakeDetector([]), ScriptedOcr([]), PlateTracker())
    assert run(pipeline, 3, frame_image) == []


def test_pipeline_caps_plates_per_frame(frame_image: Image) -> None:
    boxes = [Box(0, 0, 10, 10)] * 5
    ocr = ScriptedOcr(["DL01AB1234", "HR26DK8337"])
    pipeline = Pipeline(
        FakeDetector(boxes), ocr, PlateTracker(min_agreeing_reads=1), max_plates_per_frame=2
    )
    assert sorted(run(pipeline, 1, frame_image)) == ["DL01AB1234", "HR26DK8337"]


def test_two_line_plates_are_read_top_to_bottom() -> None:
    result = join_lines([("1234", 0.8, 40.0), ("UP16AB", 0.9, 5.0), ("", 0.1, 0.0)])
    assert result == OcrResult(text="UP16AB1234", confidence=0.8)
    assert join_lines([]) is None


@pytest.mark.parametrize("mark", ["IND", "INO", "in0", "1ND"])
def test_join_lines_drops_the_hsrp_ind_mark(mark: str) -> None:
    """Real webcam reads ended in 'IND': the mark sits below the number on the blue strip."""
    result = join_lines([("HR76A0005", 0.9, 10.0), (mark, 0.6, 30.0)])
    assert result == OcrResult("HR76A0005", 0.9)


def test_join_lines_keeps_a_lone_piece() -> None:
    assert join_lines([("IND", 0.5, 0.0)]) == OcrResult("IND", 0.5)


def test_small_crops_are_upscaled_for_ocr() -> None:
    small = np.zeros((20, 80, 3), dtype=np.uint8)
    assert prepare_crop(small).shape[:2] == (64, 256)
    big = np.zeros((100, 300, 3), dtype=np.uint8)
    assert prepare_crop(big).shape[:2] == (100, 300)


def test_image_folder_source(tmp_path: Path, frame_image: Image) -> None:
    for name in ("b.jpg", "a.png"):
        cv2.imwrite(str(tmp_path / name), frame_image)
    (tmp_path / "notes.txt").write_text("not an image")
    (tmp_path / "broken.jpg").write_bytes(b"not really a jpeg")
    frames = list(image_folder(tmp_path))
    assert len(frames) == 2
    assert frames[0].image.shape == (480, 640, 3)
    assert is_folder(str(tmp_path))


def test_video_file_source_samples_frames_with_video_time(tmp_path: Path) -> None:
    path = tmp_path / "gate.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*"MJPG"), 25, (320, 240))
    for i in range(50):  # 2 seconds of video
        writer.write(np.full((240, 320, 3), i * 5, dtype=np.uint8))
    writer.release()

    frames = list(video(str(path), sample_fps=5, start=T0))
    assert len(frames) == 10  # every 5th frame
    assert frames[1].captured_at - frames[0].captured_at == timedelta(seconds=0.2)
    assert frames[0].captured_at == T0
    assert len(list(video(str(path), sample_fps=5, start=T0, max_frames=3))) == 3


def test_source_kinds() -> None:
    assert is_live("0")
    assert is_live("rtsp://camera.local/stream")
    assert not is_live("gate.mp4")


def test_missing_sources_fail_clearly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        open_source(str(tmp_path / "missing.mp4"), 5)
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(OSError, match="Could not open"):
        list(video(str(bad), 5))
