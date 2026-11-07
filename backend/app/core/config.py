from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # .env is resolved relative to backend/, so the app works from any working directory.
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "CQA Backend"
    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    # SQLite by default; any SQLAlchemy async URL works (e.g. postgresql+asyncpg://...).
    database_url: str = f"sqlite+aiosqlite:///{BACKEND_ROOT / 'data' / 'cqa.db'}"

    # Comma-separated list of allowed origins; "*" allows all (fine for a demo).
    cors_origins: str = "*"

    # Organizer dataset API. Full URL of the GET endpoint; group_id is appended as a query param.
    organizer_api_url: str | None = None
    organizer_api_timeout_s: float = 60.0

    # ML evaluation provider.
    ml_provider: Literal["mock", "http"] = "mock"
    ml_service_url: str | None = None  # e.g. http://localhost:8001
    ml_timeout_s: float = 180.0
    ml_max_retries: int = 2

    # In-process evaluation queue.
    queue_workers: int = Field(default=3, ge=1, le=32)

    # Seed the default checklist on startup if none exist.
    seed_default_checklist: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
