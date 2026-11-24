"""Worker settings, read from environment variables (prefix ANPR_) or a .env file."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ANPR_DIR = Path(__file__).resolve().parents[1]


class AnprSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ANPR_", env_file=".env", extra="ignore")

    api_url: str = "http://127.0.0.1:8000"
    # The camera's device key from the seed script / admin API. Never commit it.
    device_key: SecretStr | None = None
    # Optional second key for an *exit* camera. With it, the live preview (--preview) can
    # switch one webcam between entry and exit (laptop demos). See docs/webcam-demo.md.
    exit_device_key: SecretStr | None = None

    detector_model: Path = ANPR_DIR / "models" / "plate_detector.onnx"
    detector_input_size: int = 640
    detector_confidence: float = Field(default=0.35, ge=0, le=1)
    detector_iou: float = Field(default=0.5, ge=0, le=1)

    ocr_engine: Literal["easyocr", "paddleocr"] = "easyocr"

    # How many frames per second to analyse (cameras send 25-30; plates don't move that fast).
    sample_fps: float = Field(default=5.0, gt=0)
    # A car's reads are grouped until its plate hasn't been seen for this long.
    track_gap_seconds: float = Field(default=2.0, gt=0)
    # Send early once this many reads agree (lower latency at the barrier).
    track_min_agreeing_reads: int = Field(default=3, ge=1)

    request_timeout_seconds: float = Field(default=10.0, gt=0)
    max_retries: int = Field(default=4, ge=0)
    # Offline mode: undeliverable reads wait here and are sent in order later.
    # An empty value turns the buffer off (reads that can't be sent are then dropped).
    buffer_path: Path | None = ANPR_DIR / "data" / "offline-buffer.sqlite3"

    @field_validator("buffer_path", mode="before")
    @classmethod
    def _empty_means_off(cls, value: object) -> object:
        # Without this, "" would become Path(".") (the current folder), not "off".
        return None if isinstance(value, str) and not value.strip() else value

    # Webcams: ask for this resolution (the camera picks the nearest it supports).
    camera_width: int = Field(default=1280, gt=0)
    camera_height: int = Field(default=720, gt=0)

    # Live preview (--preview): a local page with the camera picture and each decision.
    preview_host: str = "127.0.0.1"  # this computer only
    preview_port: int = Field(default=8765, ge=0, le=65535)
    # Where the guard console runs, for the "register this visitor" link.
    console_url: str = "http://localhost:5173"
