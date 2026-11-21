"""One frame through the whole chain: detect -> crop -> OCR -> clean -> track."""

import logging
from typing import Protocol

from gatesense_anpr.detector import crop
from gatesense_anpr.models import Detection, Frame, Image, PlateRead
from gatesense_anpr.normaliser import clean, looks_like_plate
from gatesense_anpr.ocr import OcrEngine
from gatesense_anpr.tracker import PlateTracker

logger = logging.getLogger(__name__)


class Detector(Protocol):
    def detect(self, image: Image) -> list[Detection]: ...


class Pipeline:
    def __init__(
        self,
        detector: Detector,
        ocr: OcrEngine,
        tracker: PlateTracker,
        *,
        max_plates_per_frame: int = 3,
    ) -> None:
        self.detector = detector
        self.ocr = ocr
        self.tracker = tracker
        self.max_plates_per_frame = max_plates_per_frame

    def process(self, frame: Frame) -> list[PlateRead]:
        ready: list[PlateRead] = []
        for detection in self.detector.detect(frame.image)[: self.max_plates_per_frame]:
            result = self.ocr.read(crop(frame.image, detection.box))
            if result is None:
                continue
            text = clean(result.text)
            if not looks_like_plate(text):
                logger.debug("dropped OCR text %r", result.text)
                continue
            # The API's confidence threshold is about the *text*, so send OCR confidence.
            ready += self.tracker.add(text, result.confidence, frame.captured_at, frame.image)
        ready += self.tracker.expire(frame.captured_at)
        return ready

    def finish(self) -> list[PlateRead]:
        return self.tracker.flush()
