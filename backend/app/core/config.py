from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
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
    # mock: built-in heuristics; http: the ML team's service; openai: any OpenAI-compatible API.
    ml_provider: Literal["mock", "http", "openai"] = "mock"
    ml_service_url: str | None = None  # e.g. http://localhost:8001
    ml_timeout_s: float = 180.0
    ml_max_retries: int = 2
    # Artificial latency of the mock provider, to rehearse slow-model behaviour (polling, batches).
    ml_mock_delay_s: float = Field(default=0.0, ge=0, le=300)

    # OpenAI-compatible LLM (ML_PROVIDER=openai, and bot handoff analysis when a key is set).
    # OPENAI_BASE_URL may point to a local server (Ollama: http://localhost:11434/v1).
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4.1"
    openai_temperature: float | None = 0.0  # empty for models that reject it
    # Optional: none | low | medium | high for reasoning models (cost and latency vs care).
    openai_reasoning_effort: str | None = None
    openai_timeout_s: float = 120.0
    openai_price_input_per_1m: float = 2.0
    openai_price_output_per_1m: float = 8.0
    # Mask IIN, cards, phones, e-mails and IBANs before text goes to a non-local LLM.
    pii_masking: bool = True
    # Language of model explanations: ru | kk | en.
    output_language: str = "ru"

    # Attention queue: completed evaluations below this total are flagged.
    attention_score_threshold: float = Field(default=60.0, ge=0, le=100)

    # In-process evaluation queue.
    queue_workers: int = Field(default=3, ge=1, le=32)
    # How long POST /api/evaluations waits for the result before returning the in-progress
    # evaluation. Keep it under proxy limits (Cloudflare closes requests after ~100 s).
    evaluation_wait_s: float = Field(default=85.0, ge=0, le=600)

    # Seed the default checklist on startup if none exist.
    seed_default_checklist: bool = True

    # Serve the frontend (../frontend) from the same origin: one port, one tunnel, no CORS.
    serve_frontend: bool = True
    frontend_dir: str | None = None  # defaults to <repo>/frontend

    @field_validator("openai_temperature", mode="before")
    @classmethod
    def _blank_is_none(cls, v):
        return None if isinstance(v, str) and not v.strip() else v

    @property
    def llm_configured(self) -> bool:
        local = any(h in self.openai_base_url for h in ("localhost", "127.0.0.1"))
        return bool(self.openai_api_key) or local


@lru_cache
def get_settings() -> Settings:
    return Settings()
