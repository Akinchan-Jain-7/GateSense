"""Worker settings, read from environment variables (prefix ANPR_) or a .env file."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ANPR_DIR = Path(__file__).resolve().parents[1]


class AnprSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ANPR_", env_file=".env", extra="ignore")

    api_url: str = "http://127.0.0.1:8000"
    # The camera's device key from the seed script / admin API. Never commit it.
    device_key: SecretStr | None = None

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
