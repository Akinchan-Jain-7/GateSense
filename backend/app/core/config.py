"""Application settings, read from environment variables (and the repo-root `.env`).

Every setting has a safe local-development default, so `uv run uvicorn app.main:app`
works after `cp .env.example .env`. Production refuses to start with the dev JWT secret.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> parents[3] is the repository root, where `.env` lives.
# Using an absolute path means the file is found whatever folder you run commands from.
REPO_ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

DEV_JWT_SECRET = "dev-only-insecure-jwt-secret-change-me"  # noqa: S105 - public dev default


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        # .env also holds Docker/frontend variables the backend doesn't use.
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    database_url: str = (
        "postgresql+psycopg://gatesense:gatesense_dev_password@127.0.0.1:5432/gatesense"
    )
    redis_url: str = "redis://127.0.0.1:6379/0"

    # --- Auth ---
    jwt_secret_key: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=15, ge=1)
    refresh_token_expire_days: int = Field(default=7, ge=1)

    # --- API ---
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:5173"]

    # --- Hardening (Phase 7) ---
    # Largest request body, except camera uploads (which get snapshot_max_bytes + 64 KB).
    max_request_bytes: int = Field(default=1_048_576, ge=1024)
    # Per minute. Login: per client IP and per account (slows down password guessing).
    login_rate_limit_per_ip: int = Field(default=20, ge=1)
    login_rate_limit_per_account: int = Field(default=10, ge=1)
    # Per minute, per camera key: a real camera sends a few reads a minute.
    device_rate_limit: int = Field(default=600, ge=1)
    # If set, GET /metrics needs "Authorization: Bearer <token>". Set it in production.
    metrics_token: SecretStr | None = None
    default_page_size: int = Field(default=20, ge=1)
    max_page_size: int = Field(default=100, ge=1)

    # --- Gate events ---
    # OCR reads below this confidence go to the guard review queue instead of acting.
    plate_confidence_threshold: float = Field(default=0.80, ge=0, le=1)
    # Default number of visitor parking spaces (admins can change it per society).
    visitor_parking_slots: int = Field(default=20, ge=0)
    # Max edit distance for fuzzy matching against known plates (0 = exact only).
    plate_fuzzy_max_distance: int = Field(default=1, ge=0, le=2)
    # The same plate on the same lane within this many seconds is one event (debounce).
    gate_event_cooldown_seconds: int = Field(default=30, ge=1)
    # Reject capture times this far in the future (camera clock drift beyond this = bug).
    gate_event_max_clock_skew_seconds: int = Field(default=300, ge=0)

    # --- Visit time limits (defaults; Phase 4 makes them admin-configurable) ---
    visit_limit_guest_minutes: int = Field(default=240, ge=1)
    visit_limit_delivery_minutes: int = Field(default=20, ge=1)
    visit_limit_cab_minutes: int = Field(default=10, ge=1)
    # Service visits normally get a resident-set duration; this is the fallback.
    visit_limit_service_minutes: int = Field(default=120, ge=1)

    # --- Approvals ---
    # How long residents get to answer before the guard decides (default 3 minutes).
    approval_timeout_seconds: int = Field(default=180, ge=10)

    # --- Overstay escalation ladder (minutes after the time limit) ---
    overstay_reminder_minutes: int = Field(default=30, ge=1)
    overstay_escalation_minutes: int = Field(default=60, ge=1)
    # Visitors still "inside" this long after their limit are flagged by reconciliation.
    reconciliation_stale_hours: int = Field(default=24, ge=1)

    # --- Privacy ---
    visitor_retention_days: int = Field(default=90, ge=1)

    # --- Email (Mailpit catches everything in development) ---
    smtp_host: str = "127.0.0.1"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = False
    smtp_from: str = "GateSense <noreply@gatesense.local>"
    # Where visitors' "time remaining" links point (the API's public URL).
    public_base_url: str = "http://127.0.0.1:8000"
    notification_max_attempts: int = Field(default=5, ge=1)

    # --- Telegram bot (optional; leave the token empty to turn the bot off) ---
    telegram_bot_token: SecretStr | None = None
    telegram_bot_username: str | None = None  # e.g. GateSenseDemoBot, for the deep link
    # Telegram sends it back in a header with every webhook call; we reject calls without it.
    telegram_webhook_secret: SecretStr | None = None
    telegram_api_url: str = "https://api.telegram.org"

    # --- Plate snapshots ---
    # "local": files in snapshot_local_dir. "s3": any S3-compatible store (RustFS in dev).
    snapshot_storage: Literal["local", "s3"] = "local"
    snapshot_local_dir: Path = REPO_ROOT_ENV_FILE.parent / "data" / "snapshots"
    snapshot_max_bytes: int = Field(default=2_000_000, ge=1)
    s3_endpoint_url: str | None = "http://127.0.0.1:9000"
    s3_bucket: str = "gatesense-snapshots"
    s3_region: str = "us-east-1"
    s3_access_key: str = "gatesense"
    s3_secret_key: str = "gatesense_dev_secret"  # noqa: S105 - public dev default

    # --- Demo data ---
    # Password for every seeded demo account. Public on purpose: the live demo shows it.
    demo_password: str = "GateSense@123"  # noqa: S105
    # Demo mode: the landing page shows one-click demo logins and admins can reset the data.
    # Turn it on for the public demo only; never on a real society's deployment.
    demo_mode: bool = False

    @model_validator(mode="after")
    def _refuse_dev_secret_in_production(self) -> "Settings":
        if self.app_env == "production" and self.jwt_secret_key == DEV_JWT_SECRET:
            raise ValueError("JWT_SECRET_KEY must be set to a real secret in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """Settings are read once and cached; tests can call `get_settings.cache_clear()`."""
    return Settings()
