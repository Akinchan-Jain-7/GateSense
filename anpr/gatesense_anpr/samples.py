"""Labelled test photos from the live preview ("Save for testing").

Real accuracy needs real photos with the right answer written down. Collecting them by
hand is slow, so the preview page can save the current camera frame together with the
plate you type in. The folder uses the layout `eval/evaluate_pipeline.py` reads
(anpr/DATASET.md):

    data/eval/webcam/
    ├── labels.csv            file,plate,condition
    ├── phone/0001.jpg        a plate shown on a phone screen
    ├── printed/0001.jpg      a printed plate
    └── ...

Then: `uv run python eval/evaluate_pipeline.py data/eval/webcam --name e2e_webcam`.

Photos of plates are personal data: the folder is under anpr/data/, which git ignores.
"""

import csv
import threading
from collections import Counter
from pathlib import Path

import cv2

from gatesense_anpr.models import Image
from gatesense_anpr.normaliser import clean, looks_like_plate

# What was in front of the camera. Kept short so the results table stays readable.
CONDITIONS = {
    "phone": "a plate on a phone screen",
    "printed": "a printed plate",
    "car": "a real car, or a photo of a whole car",
    "dim": "low light",
    "angled": "held at an angle",
}
HEADER = ["file", "plate", "condition"]


class SampleError(ValueError):
    pass


class SampleStore:
    """Appends photos and their labels to a labels.csv folder; safe to use from threads."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.labels = root / "labels.csv"
        self._lock = threading.Lock()
        self.counts: Counter[str] = Counter()
        if self.labels.exists():
            with self.labels.open(newline="", encoding="utf-8") as file:
                self.counts.update(row["condition"] for row in csv.DictReader(file))

    def save(self, image: Image, plate: str, condition: str) -> str:
        """Save `image` labelled with `plate`; returns its path relative to the folder."""
        plate = clean(plate)
        if not looks_like_plate(plate):
            raise SampleError("Type the plate exactly as written, e.g. DL01AB1234")
        if condition not in CONDITIONS:
            raise SampleError(f"Condition must be one of: {', '.join(CONDITIONS)}")
        with self._lock:
            folder = self.root / condition
            folder.mkdir(parents=True, exist_ok=True)
            number = len(list(folder.glob("*.jpg"))) + 1
            while (folder / f"{number:04d}.jpg").exists():
                number += 1
            relative = f"{condition}/{number:04d}.jpg"
            if not cv2.imwrite(str(self.root / relative), image, [cv2.IMWRITE_JPEG_QUALITY, 95]):
                raise OSError(f"Could not write {self.root / relative}")
            new_file = not self.labels.exists()
            with self.labels.open("a", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                if new_file:
                    writer.writerow(HEADER)
                writer.writerow([relative, plate, condition])
            self.counts[condition] += 1
            return relative

    def summary(self) -> dict[str, int]:
        with self._lock:
            return dict(self.counts)
