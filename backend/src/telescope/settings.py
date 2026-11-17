from typing import Any, Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    github_token: SecretStr | None = None
    github_api_url: str = "https://api.github.com"
    github_timeout_s: float = 10.0
    github_max_retries: int = 3
    github_page_concurrency: int = 8
    cache_ttl_seconds: int = 600
    cache_backend: Literal["memory", "redis"] = "memory"
    redis_url: str = "redis://localhost:6379/0"
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:5173"]

    @field_validator("github_token", mode="before")
    @classmethod
    def _empty_token_is_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value
