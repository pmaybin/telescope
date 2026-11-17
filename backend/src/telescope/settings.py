from typing import Any

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
    cache_ttl_seconds: int = 600
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:5173"]

    @field_validator("github_token", mode="before")
    @classmethod
    def _empty_token_is_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value
