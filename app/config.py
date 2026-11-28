"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "uk", "ru", "de")
DEFAULT_LANGUAGE = "en"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_base_url: str = "http://localhost:8000"
    log_level: str = "INFO"

    telegram_bot_token: str = ""
    bot_mode: Literal["polling", "webhook"] = "polling"
    telegram_webhook_secret: str = ""

    ai_provider: Literal["openai", "gemini", "mock"] = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    openai_transcription_model: str = "whisper-1"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    ai_timeout_seconds: float = 90.0

    database_url: str = "postgresql+asyncpg://copilot:copilot@localhost:5432/copilot"
    redis_url: str = "redis://localhost:6379/0"

    job_search_provider: str = ""
    job_search_api_key: str = ""

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""

    storage_backend: Literal["local", "s3"] = "local"
    local_storage_path: str = "./var/storage"
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "ai-job-copilot"
    s3_region: str = "us-east-1"

    encryption_key: str = ""
    admin_telegram_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)

    free_application_limit: int = 5
    daily_application_limit: int = 20

    rate_limit_events: int = 30
    rate_limit_window_seconds: int = 10

    max_upload_mb: int = 10
    ocr_languages: str = "eng+deu+ukr+rus"
    privacy_policy_version: str = "2026-11-01"
    support_contact: str = "@your_support_account"

    mock_mode: bool = False

    @field_validator("admin_telegram_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(v) for v in value.replace(" ", "").split(",") if v]
        if isinstance(value, int):
            return [value]
        return value

    @model_validator(mode="after")
    def _production_guards(self) -> "Settings":
        if self.app_env == "production":
            if self.mock_mode or self.ai_provider == "mock":
                raise ValueError("MOCK_MODE / AI_PROVIDER=mock is forbidden in production")
            if not self.encryption_key:
                raise ValueError("ENCRYPTION_KEY is required in production")
            if not self.app_base_url.startswith("https://"):
                raise ValueError("APP_BASE_URL must use HTTPS in production")
        return self

    @property
    def effective_ai_provider(self) -> str:
        return "mock" if self.mock_mode else self.ai_provider

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
