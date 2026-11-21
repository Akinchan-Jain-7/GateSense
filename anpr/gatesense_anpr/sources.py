"""Where frames come from: a camera (USB index or RTSP/HTTP URL), a video file, or a folder.

Every source yields `Frame`s at roughly `sample_fps`. Capture times:
- live cameras: the wall clock when the frame was read;
- video files: start time + the frame's position in the video, so replaying a recording
  gives the same timings every run (and the server debounce sees realistic gaps);
- image folders: each image is treated as a separate sighting (see `is_folder`).
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

from gatesense_anpr.models import Frame

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def is_folder(spec: str) -> bool:
    return Path(spec).is_dir()


def is_live(spec: str) -> bool:
    return spec.isdigit() or spec.startswith(("rtsp://", "rtsps://", "http://", "https://"))


def image_folder(path: Path) -> Iterator[Frame]:
    for image_path in sorted(p for p in path.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES):
        image = cv2.imread(str(image_path))
        if image is None:
            continue
        yield Frame(image=np.asarray(image, dtype=np.uint8), captured_at=datetime.now(UTC))


def video(
    spec: str, sample_fps: float, *, start: datetime | None = None, max_frames: int | None = None
) -> Iterator[Frame]:
    live = is_live(spec)
    capture = cv2.VideoCapture(int(spec) if spec.isdigit() else spec)
    if not capture.isOpened():
        raise OSError(f"Could not open video source {spec!r}")
    video_fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, round(video_fps / sample_fps))
    start = start or datetime.now(UTC)
    index = yielded = 0
    try:
        while max_frames is None or yielded < max_frames:
            ok, image = capture.read()
            if not ok:
                break
            if index % step == 0:
                at = datetime.now(UTC) if live else start + timedelta(seconds=index / video_fps)
                yield Frame(image=np.asarray(image, dtype=np.uint8), captured_at=at)
                yielded += 1
            index += 1
    finally:
        capture.release()


def open_source(spec: str, sample_fps: float) -> Iterator[Frame]:
    if is_folder(spec):
        return image_folder(Path(spec))
    if not is_live(spec) and not Path(spec).exists():
        raise FileNotFoundError(f"No such video file or folder: {spec}")
    return video(spec, sample_fps)
