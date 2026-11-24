"""Where frames come from: a camera (USB index or RTSP/HTTP URL), a video file, or a folder.

Every source yields `Frame`s at roughly `sample_fps`. Capture times:
- live cameras: the wall clock when the frame was read;
- video files: start time + the frame's position in the video, so replaying a recording
  gives the same timings every run (and the server debounce sees realistic gaps);
- image folders: each image is treated as a separate sighting (see `is_folder`).
"""

import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

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


def open_capture(spec: str, *, width: int | None = None, height: int | None = None) -> Any:
    """Open a camera index, stream URL or video file with OpenCV.

    Webcams (a number) on Windows open through DirectShow first: the default backend
    (Media Foundation) can take 10+ seconds to start a laptop camera. For webcams we also
    ask for `width` x `height`; the camera picks the nearest size it supports.
    """
    if spec.isdigit():
        index = int(spec)
        capture = None
        if sys.platform == "win32":
            capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
            if not capture.isOpened():
                capture.release()
                capture = None
        if capture is None:
            capture = cv2.VideoCapture(index)
        if width and height:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    else:
        capture = cv2.VideoCapture(spec)
    if not capture.isOpened():
        capture.release()
        hint = " (is another app using the camera?)" if spec.isdigit() else ""
        raise OSError(f"Could not open video source {spec!r}{hint}")
    return capture


def video(
    spec: str, sample_fps: float, *, start: datetime | None = None, max_frames: int | None = None
) -> Iterator[Frame]:
    live = is_live(spec)
    capture = open_capture(spec)
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
