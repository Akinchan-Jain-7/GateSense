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

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

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


type Voting = Literal["string", "chars"]


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

    def fused(self) -> tuple[str, _Candidate, bool]:
        """Per-character vote over the reads of the most likely length.

        Returns the voted text, a candidate summing that length's reads, and whether every
        position has a clear majority (at least 2 of 3 reads agree), i.e. it's safe to send
        early. Frames rarely all misread the *same* character, so a per-position vote can
        recover the plate even when no single frame read all of it correctly.
        """
        by_length: dict[int, list[tuple[str, _Candidate]]] = defaultdict(list)
        for text, candidate in self.candidates.items():
            by_length[len(text)].append((text, candidate))
        group = max(
            by_length.values(),
            key=lambda g: (sum(c.total_confidence for _, c in g), sum(c.count for _, c in g)),
        )
        chars: list[str] = []
        clear = True
        for position in range(len(group[0][0])):
            weight: defaultdict[str, float] = defaultdict(float)
            reads: Counter[str] = Counter()
            for text, candidate in group:
                weight[text[position]] += candidate.total_confidence
                reads[text[position]] += candidate.count
            best = max(weight, key=lambda char: (weight[char], reads[char]))
            chars.append(best)
            clear &= 3 * reads[best] >= 2 * sum(reads.values())
        merged = _Candidate(
            total_confidence=sum(c.total_confidence for _, c in group),
            count=sum(c.count for _, c in group),
            first_seen=min(c.first_seen for _, c in group if c.first_seen is not None),
        )
        _, sharpest = max(group, key=lambda tc: tc[1].best_confidence)
        merged.best_confidence, merged.best_image = sharpest.best_confidence, sharpest.best_image
        return "".join(chars), merged, clear

    def raw_texts(self) -> tuple[str, ...]:
        return tuple(sorted(self.candidates))


class PlateTracker:
    def __init__(
        self,
        *,
        gap_seconds: float = 2.0,
        min_agreeing_reads: int = 3,
        max_distance: int = 1,
        voting: Voting = "string",
    ) -> None:
        self.gap = timedelta(seconds=gap_seconds)
        self.min_agreeing_reads = min_agreeing_reads
        self.max_distance = max_distance
        self.voting = voting
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

        best_text, best, ready_now = self._decide(track)
        if not track.sent and ready_now:
            track.sent = True
            ready.append(self._to_read(track, best_text, best))
        return ready

    def _decide(self, track: _Track) -> tuple[str, _Candidate, bool]:
        """The track's text so far, and whether to send it now (before the car leaves)."""
        if self.voting == "chars":
            text, merged, clear = track.fused()
            enough = merged.count >= self.min_agreeing_reads
            # A plate that keeps flickering on one character is sent once it has been
            # seen plenty, with the per-position vote's best guess.
            return text, merged, enough and (clear or merged.count >= 3 * self.min_agreeing_reads)
        text, best = track.winner()
        return text, best, best.count >= self.min_agreeing_reads

    def expire(self, now: datetime) -> list[PlateRead]:
        """Close tracks not seen for `gap_seconds`; send the ones not sent yet."""
        ready: list[PlateRead] = []
        still_open: list[_Track] = []
        for track in self.tracks:
            if now - track.last_seen >= self.gap:
                if not track.sent:
                    text, candidate, _ = self._decide(track)
                    ready.append(self._to_read(track, text, candidate))
            else:
                still_open.append(track)
        self.tracks = still_open
        return ready

    def flush(self) -> list[PlateRead]:
        """End of input: send everything still pending."""
        ready = [self._to_read(t, *self._decide(t)[:2]) for t in self.tracks if not t.sent]
        self.tracks = []
        return ready

    def reset(self) -> None:
        """Forget every open track without sending it (the live preview's "scan again")."""
        self.tracks = []

    def _find_track(self, text: str) -> _Track | None:
        # Per-character voting needs the reads that are wrong in *different* places in one
        # track (DL01AB1Z34 and DL0IAB1234 are 2 apart), so it groups one edit more loosely.
        limit = self.max_distance + (1 if self.voting == "chars" else 0)
        best: tuple[int, _Track] | None = None
        for track in self.tracks:
            distance = min(edit_distance(text, known) for known in track.candidates)
            if distance <= limit and (best is None or distance < best[0]):
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
