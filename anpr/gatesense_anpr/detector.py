"""Plate detector: a YOLOv8 model exported to ONNX, run with ONNX Runtime.

We don't import Ultralytics (or PyTorch) at run time. The three steps around the model
are small and written here in NumPy, so the edge machine only needs onnxruntime:

1. `letterbox`: resize the frame to the model's square input without stretching it,
   padding the rest with grey (what YOLO was trained on).
2. the model: one tensor of shape (1, 4 + classes, N): for each of N candidate boxes,
   centre x, centre y, width, height, then one score per class.
3. `decode_yolov8` + `nms`: keep confident boxes, map them back to frame pixels, and
   drop overlapping duplicates (non-maximum suppression).
"""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import numpy.typing as npt

from gatesense_anpr.models import Box, Detection, Image

type FloatArray = npt.NDArray[np.float32]


@dataclass(frozen=True)
class Letterbox:
    """How a frame was fitted into the model input, so boxes can be mapped back."""

    scale: float
    pad_x: float
    pad_y: float


def letterbox(image: Image, size: int) -> tuple[FloatArray, Letterbox]:
    """Frame (H x W x 3, BGR) -> model input (1 x 3 x size x size, RGB, 0..1)."""
    height, width = image.shape[:2]
    scale = min(size / height, size / width)
    new_w, new_h = round(width * scale), round(height * scale)
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    pad_x, pad_y = (size - new_w) / 2, (size - new_h) / 2
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)  # YOLO's grey padding
    top, left = round(pad_y - 0.1), round(pad_x - 0.1)
    canvas[top : top + new_h, left : left + new_w] = resized
    tensor = canvas[:, :, ::-1].transpose(2, 0, 1)[np.newaxis].astype(np.float32) / 255.0
    return np.ascontiguousarray(tensor), Letterbox(scale=scale, pad_x=left, pad_y=top)


def iou(box: FloatArray, others: FloatArray) -> FloatArray:
    """Intersection over union of one [x1, y1, x2, y2] box with each row of `others`."""
    x1 = np.maximum(box[0], others[:, 0])
    y1 = np.maximum(box[1], others[:, 1])
    x2 = np.minimum(box[2], others[:, 2])
    y2 = np.minimum(box[3], others[:, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area = (box[2] - box[0]) * (box[3] - box[1])
    areas = (others[:, 2] - others[:, 0]) * (others[:, 3] - others[:, 1])
    result: FloatArray = inter / np.maximum(area + areas - inter, 1e-9)
    return result


def nms(boxes: FloatArray, scores: FloatArray, iou_threshold: float) -> list[int]:
    """Indices of boxes to keep: best first, dropping any that overlap a kept one too much."""
    order = list(np.argsort(-scores))
    keep: list[int] = []
    while order:
        best = int(order.pop(0))
        keep.append(best)
        if not order:
            break
        rest = np.array(order)
        overlaps = iou(boxes[best], boxes[rest])
        order = [int(i) for i, o in zip(rest, overlaps, strict=True) if o <= iou_threshold]
    return keep


def decode_yolov8(
    output: FloatArray,
    geometry: Letterbox,
    frame_shape: tuple[int, int],
    *,
    confidence: float,
    iou_threshold: float,
) -> list[Detection]:
    """Model output (1, 4 + classes, N) -> detections in frame pixels, best first."""
    predictions = output[0].T  # (N, 4 + classes)
    scores = predictions[:, 4:].max(axis=1)
    confident = scores >= confidence
    if not confident.any():
        return []
    predictions, scores = predictions[confident], scores[confident]

    cx, cy, w, h = predictions[:, 0], predictions[:, 1], predictions[:, 2], predictions[:, 3]
    boxes = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)
    # Undo the letterbox: remove padding, undo scaling, clip to the frame.
    boxes[:, [0, 2]] = (boxes[:, [0, 2]] - geometry.pad_x) / geometry.scale
    boxes[:, [1, 3]] = (boxes[:, [1, 3]] - geometry.pad_y) / geometry.scale
    height, width = frame_shape
    boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, width)
    boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, height)

    return [
        Detection(box=Box(*(float(v) for v in boxes[i])), score=float(scores[i]))
        for i in nms(boxes.astype(np.float32), scores.astype(np.float32), iou_threshold)
    ]


def crop(image: Image, box: Box, margin: float = 0.05) -> Image:
    """The plate region, with a small margin so OCR doesn't lose edge characters."""
    height, width = image.shape[:2]
    mx, my = (box.x2 - box.x1) * margin, (box.y2 - box.y1) * margin
    x1, y1 = max(0, int(box.x1 - mx)), max(0, int(box.y1 - my))
    x2, y2 = min(width, int(box.x2 + mx)), min(height, int(box.y2 + my))
    return image[y1:y2, x1:x2]


class PlateDetector:
    def __init__(
        self,
        model_path: Path,
        *,
        input_size: int = 640,
        confidence: float = 0.35,
        iou_threshold: float = 0.5,
    ) -> None:
        import onnxruntime as ort  # imported here so tests of the helpers don't need it

        if not model_path.exists():
            raise FileNotFoundError(
                f"No detector model at {model_path}. Train/export one with "
                "notebooks/01_train_plate_detector.ipynb or run `python -m "
                "gatesense_anpr.download_model` (see anpr/README.md)."
            )
        self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.input_size = input_size
        self.confidence = confidence
        self.iou_threshold = iou_threshold

    def detect(self, image: Image) -> list[Detection]:
        tensor, geometry = letterbox(image, self.input_size)
        (output,) = self.session.run(None, {self.input_name: tensor})[:1]
        return decode_yolov8(
            np.asarray(output, dtype=np.float32),
            geometry,
            (image.shape[0], image.shape[1]),
            confidence=self.confidence,
            iou_threshold=self.iou_threshold,
        )
