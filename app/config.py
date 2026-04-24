from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://annotations:annotations@localhost:5432/annotations"
    upload_dir: Path = Path("/data/uploads")
    max_file_size_bytes: int = 25 * 1024 * 1024

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    annotator_mode: Literal["openai", "anthropic", "mock"] = "openai"
    annotator_model: str = "gpt-4o-mini"

    cors_origins: str = Field(
        default="http://localhost:3000,http://localhost:5173,http://localhost:8000"
    )
    worker_id: str = "worker-1"
    worker_poll_interval_seconds: float = 1.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def validate_provider_config(self) -> None:
        if self.annotator_mode == "openai" and not self.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is required unless ANNOTATOR_MODE=mock. "
                "Copy .env.example to .env and either set OPENAI_API_KEY or set ANNOTATOR_MODE=mock."
            )
        if self.annotator_mode == "anthropic" and not self.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is required when ANNOTATOR_MODE=anthropic. "
                "Copy .env.example to .env and either set ANTHROPIC_API_KEY or set ANNOTATOR_MODE=mock."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
