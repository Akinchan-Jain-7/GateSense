"""Application settings, read from environment variables (and the repo-root `.env`).

Every setting has a safe local-development default, so `uv run uvicorn app.main:app`
works after `cp .env.example .env`. Production refuses to start with the dev JWT secret.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
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
        "postgresql+psycopg://gatesense:gatesense_dev_password@localhost:5432/gatesense"
    )
    redis_url: str = "redis://localhost:6379/0"

    # --- Auth ---
    jwt_secret_key: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=15, ge=1)
    refresh_token_expire_days: int = Field(default=7, ge=1)

    # --- API ---
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:5173"]
    default_page_size: int = Field(default=20, ge=1)
    max_page_size: int = Field(default=100, ge=1)

    # --- Demo data ---
    # Password for every seeded demo account. Public on purpose: the live demo shows it.
    demo_password: str = "GateSense@123"  # noqa: S105

    @model_validator(mode="after")
    def _refuse_dev_secret_in_production(self) -> "Settings":
        if self.app_env == "production" and self.jwt_secret_key == DEV_JWT_SECRET:
            raise ValueError("JWT_SECRET_KEY must be set to a real secret in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """Settings are read once and cached; tests can call `get_settings.cache_clear()`."""
    return Settings()
