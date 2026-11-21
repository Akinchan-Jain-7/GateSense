"""Group the reads of one car across video frames and send it once.

A car at the barrier is in view for a second or more: dozens of frames, and OCR rarely
reads every frame the same (`DL01AB1234`, `DL01AB1Z34`, `DL01A81234`…). The tracker:

- puts a read into an open *track* if its text is within one edit of the track's best
  text, otherwise starts a new track;
- **votes**: each distinct text scores the sum of its OCR confidences; the top one wins;
- **sends early** once `min_agreeing_reads` frames agree on the winning text (the barrier
  shouldn't wait for the car to leave the frame), and stays quiet for the rest of the track;
- otherwise sends when the plate hasn't been seen for `gap_seconds` (or at end of input).

This removes most near-duplicates before they reach the server, whose own debounce
(ADR-0006) is exact-match only.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import cv2
import numpy as np

from gatesense_anpr.models import Image, PlateRead
from gatesense_anpr.normaliser import edit_distance

SNAPSHOT_MAX_WIDTH = 1280
SNAPSHOT_JPEG_QUALITY = 80


def encode_snapshot(image: Image) -> bytes:
    """JPEG of the whole frame (the guard wants context, not just the plate), kept small."""
    height, width = image.shape[:2]
    if width > SNAPSHOT_MAX_WIDTH:
        scale = SNAPSHOT_MAX_WIDTH / width
        image = np.asarray(
            cv2.resize(image, (SNAPSHOT_MAX_WIDTH, round(height * scale))), dtype=np.uint8
        )
    ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, SNAPSHOT_JPEG_QUALITY])
    if not ok:
        raise ValueError("Could not encode snapshot as JPEG")
    return bytes(buffer)


@dataclass
class _Candidate:
    total_confidence: float = 0.0
    count: int = 0
    first_seen: datetime | None = None
    best_confidence: float = -1.0
    best_image: Image | None = None


@dataclass
class _Track:
    last_seen: datetime
    candidates: dict[str, _Candidate] = field(default_factory=lambda: defaultdict(_Candidate))
    sent: bool = False

    def winner(self) -> tuple[str, _Candidate]:
        return max(self.candidates.items(), key=lambda kv: (kv[1].total_confidence, kv[1].count))

    def raw_texts(self) -> tuple[str, ...]:
        return tuple(sorted(self.candidates))


class PlateTracker:
    def __init__(
        self, *, gap_seconds: float = 2.0, min_agreeing_reads: int = 3, max_distance: int = 1
    ) -> None:
        self.gap = timedelta(seconds=gap_seconds)
        self.min_agreeing_reads = min_agreeing_reads
        self.max_distance = max_distance
        self.tracks: list[_Track] = []

    def add(self, text: str, confidence: float, at: datetime, image: Image) -> list[PlateRead]:
        """Record one read. Returns plates ready to send (from expired tracks or this one)."""
        ready = self.expire(at)
        track = self._find_track(text)
        if track is None:
            track = _Track(last_seen=at)
            self.tracks.append(track)
        track.last_seen = max(track.last_seen, at)

        candidate = track.candidates[text]
        candidate.total_confidence += confidence
        candidate.count += 1
        candidate.first_seen = candidate.first_seen or at
        if confidence > candidate.best_confidence:
            candidate.best_confidence, candidate.best_image = confidence, image

        best_text, best = track.winner()
        if not track.sent and best.count >= self.min_agreeing_reads:
            track.sent = True
            ready.append(self._to_read(track, best_text, best))
        return ready

    def expire(self, now: datetime) -> list[PlateRead]:
        """Close tracks not seen for `gap_seconds`; send the ones not sent yet."""
        ready: list[PlateRead] = []
        still_open: list[_Track] = []
        for track in self.tracks:
            if now - track.last_seen >= self.gap:
                if not track.sent:
                    ready.append(self._to_read(track, *track.winner()))
            else:
                still_open.append(track)
        self.tracks = still_open
        return ready

    def flush(self) -> list[PlateRead]:
        """End of input: send everything still pending."""
        ready = [self._to_read(t, *t.winner()) for t in self.tracks if not t.sent]
        self.tracks = []
        return ready

    def _find_track(self, text: str) -> _Track | None:
        best: tuple[int, _Track] | None = None
        for track in self.tracks:
            distance = min(edit_distance(text, known) for known in track.candidates)
            if distance <= self.max_distance and (best is None or distance < best[0]):
                best = (distance, track)
        return best[1] if best else None

    def _to_read(self, track: _Track, text: str, candidate: _Candidate) -> PlateRead:
        assert candidate.first_seen is not None  # noqa: S101 - set on the first read
        image = candidate.best_image
        return PlateRead(
            plate_text=text,
            confidence=round(candidate.total_confidence / candidate.count, 4),
            captured_at=candidate.first_seen,
            snapshot_jpeg=encode_snapshot(image) if image is not None else None,
            votes=candidate.count,
            raw_texts=track.raw_texts(),
        )
