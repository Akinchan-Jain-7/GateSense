"""One frame through the whole chain: detect -> crop -> OCR -> clean -> track."""

import logging
from dataclasses import dataclass
from typing import Protocol

from gatesense_anpr.detector import crop
from gatesense_anpr.models import Box, Detection, Frame, Image, PlateRead
from gatesense_anpr.normaliser import clean, looks_like_plate
from gatesense_anpr.ocr import OcrEngine, enhance_contrast
from gatesense_anpr.tracker import PlateTracker

logger = logging.getLogger(__name__)


class Detector(Protocol):
    def detect(self, image: Image) -> list[Detection]: ...


@dataclass(frozen=True)
class Sighting:
    """One plate the detector found in the last frame, and what OCR made of it.

    Used by the live preview to draw boxes; `text` is None when OCR gave nothing usable.
    """

    box: Box
    score: float
    text: str | None


class Pipeline:
    def __init__(
        self,
        detector: Detector,
        ocr: OcrEngine,
        tracker: PlateTracker,
        *,
        max_plates_per_frame: int = 3,
        contrast: bool = False,
    ) -> None:
        self.detector = detector
        self.ocr = ocr
        self.tracker = tracker
        self.max_plates_per_frame = max_plates_per_frame
        self.contrast = contrast
        # What the last processed frame contained (for the live preview's boxes).
        self.last_sightings: list[Sighting] = []

    def process(self, frame: Frame) -> list[PlateRead]:
        ready: list[PlateRead] = []
        sightings: list[Sighting] = []
        for detection in self.detector.detect(frame.image)[: self.max_plates_per_frame]:
            plate = crop(frame.image, detection.box)
            result = self.ocr.read(enhance_contrast(plate) if self.contrast else plate)
            text = clean(result.text) if result is not None else ""
            if result is None or not looks_like_plate(text):
                if result is not None:
                    logger.debug("dropped OCR text %r", result.text)
                sightings.append(Sighting(detection.box, detection.score, None))
                continue
            sightings.append(Sighting(detection.box, detection.score, text))
            # The API's confidence threshold is about the *text*, so send OCR confidence.
            ready += self.tracker.add(text, result.confidence, frame.captured_at, frame.image)
        ready += self.tracker.expire(frame.captured_at)
        self.last_sightings = sightings
        return ready

    def finish(self) -> list[PlateRead]:
        return self.tracker.flush()
