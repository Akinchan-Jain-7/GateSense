from pathlib import Path

import numpy as np
import pytest

from gatesense_anpr.detector import (
    Letterbox,
    PlateDetector,
    crop,
    decode_yolov8,
    iou,
    letterbox,
    nms,
)
from gatesense_anpr.models import Box, Image
from tests.conftest import make_constant_onnx


def yolo_output(*boxes: tuple[float, float, float, float, float]) -> np.ndarray:
    """(1, 5, N) like a 1-class YOLOv8: rows cx, cy, w, h, score; one column per box."""
    return np.array([list(b) for b in boxes], dtype=np.float32).T[np.newaxis]


def test_letterbox_keeps_aspect_ratio_and_pads(frame_image: Image) -> None:
    tensor, geometry = letterbox(frame_image, 640)  # 640x480 frame
    assert tensor.shape == (1, 3, 640, 640)
    assert tensor.dtype == np.float32
    assert tensor.min() >= 0.0 and tensor.max() <= 1.0
    assert geometry.scale == 1.0
    assert (geometry.pad_x, geometry.pad_y) == (0, 80)  # grey bars top and bottom
    assert tensor[0, 0, 0, 0] == pytest.approx(114 / 255)  # padding
    assert tensor[0, 0, 320, 320] == pytest.approx(100 / 255)  # image


def test_letterbox_downscales_large_frames() -> None:
    _, geometry = letterbox(np.zeros((1080, 1920, 3), dtype=np.uint8), 640)
    assert geometry.scale == pytest.approx(640 / 1920)
    assert geometry.pad_x == 0
    assert geometry.pad_y == 140


def test_iou() -> None:
    box = np.array([0, 0, 10, 10], dtype=np.float32)
    others = np.array([[0, 0, 10, 10], [5, 0, 15, 10], [20, 20, 30, 30]], dtype=np.float32)
    assert iou(box, others).tolist() == pytest.approx([1.0, 50 / 150, 0.0])


def test_nms_drops_overlapping_boxes() -> None:
    boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], dtype=np.float32)
    scores = np.array([0.8, 0.9, 0.7], dtype=np.float32)
    assert nms(boxes, scores, iou_threshold=0.5) == [1, 2]


def test_decode_maps_boxes_back_to_the_frame() -> None:
    # A plate centred at (320, 300) in model space, 200x60, on a frame padded by 80 px.
    output = yolo_output((320, 300, 200, 60, 0.9), (100, 100, 50, 20, 0.1))
    detections = decode_yolov8(
        output,
        Letterbox(scale=1.0, pad_x=0, pad_y=80),
        (480, 640),
        confidence=0.35,
        iou_threshold=0.5,
    )
    assert len(detections) == 1  # the 0.1 box is below the threshold
    box = detections[0].box
    assert (box.x1, box.y1, box.x2, box.y2) == pytest.approx((220, 190, 420, 250))
    assert detections[0].score == pytest.approx(0.9)


def test_decode_with_nothing_confident() -> None:
    output = yolo_output((10, 10, 5, 5, 0.01))
    assert (
        decode_yolov8(output, Letterbox(1, 0, 0), (480, 640), confidence=0.5, iou_threshold=0.5)
        == []
    )


def test_decode_clips_to_the_frame() -> None:
    output = yolo_output((5, 5, 40, 40, 0.9))
    (detection,) = decode_yolov8(
        output, Letterbox(1, 0, 0), (480, 640), confidence=0.5, iou_threshold=0.5
    )
    assert (detection.box.x1, detection.box.y1) == (0, 0)


def test_crop_adds_a_small_margin(frame_image: Image) -> None:
    piece = crop(frame_image, Box(100, 100, 300, 160), margin=0.05)
    assert piece.shape[:2] == (66, 220)
    edge = crop(frame_image, Box(0, 0, 50, 20))
    assert edge.shape[:2] == (21, 52)


def test_detector_runs_an_onnx_model(tmp_path: Path, frame_image: Image) -> None:
    model = make_constant_onnx(
        tmp_path / "plate.onnx", yolo_output((320, 300, 200, 60, 0.9), (325, 302, 200, 60, 0.8))
    )
    detector = PlateDetector(model)
    detections = detector.detect(frame_image)
    assert len(detections) == 1  # the two overlapping boxes became one
    assert detections[0].box.y1 == pytest.approx(190)


def test_missing_model_explains_how_to_get_one(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="download_model"):
        PlateDetector(tmp_path / "nope.onnx")
