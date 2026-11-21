"""Small data types passed between the pipeline stages."""

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import numpy.typing as npt

type Image = npt.NDArray[np.uint8]  # OpenCV image: height x width x 3 (BGR)


@dataclass(frozen=True)
class Box:
    """A rectangle in pixel coordinates (x1, y1) top-left to (x2, y2) bottom-right."""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def area(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)


@dataclass(frozen=True)
class Detection:
    box: Box
    score: float


@dataclass(frozen=True)
class Frame:
    image: Image
    captured_at: datetime


@dataclass(frozen=True)
class OcrResult:
    text: str
    confidence: float


@dataclass(frozen=True)
class PlateRead:
    """One plate, ready to send: the voted text, its confidence and the best snapshot."""

    plate_text: str
    confidence: float
    captured_at: datetime
    snapshot_jpeg: bytes | None = None
    # How many frames supported this text (for logs and evaluation).
    votes: int = 1
    raw_texts: tuple[str, ...] = field(default_factory=tuple)
