import json
from typing import Annotated, Any, Literal, Self

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

AuthMode = Literal["dev", "jwt", "tailscale", "none"]


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
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    # Authentication and quota protection (ADR-0013).
    auth_mode: AuthMode = "dev"
    auth_dev_secret: SecretStr | None = None
    auth_jwks_url: str | None = None
    auth_jwt_issuer: str | None = None
    auth_jwt_audience: str | None = None
    auth_trusted_proxies: Annotated[list[str], NoDecode] = []
    user_rate_per_min: float = 120
    user_rate_burst: int = 30
    user_upstream_budget: int = 100
    user_upstream_window_s: float = 600
    upstream_reserve_fraction: float = 0.2
    max_concurrent_walks: int = 2
    org_allowlist: Annotated[list[str], NoDecode] = []

    # Progressive cold load (ADR-0012).
    cold_wait_ms: int = 1500
    preview_mode: Literal["off", "first", "per-query"] = "first"
    prewarm_orgs: Annotated[list[str], NoDecode] = []

    @field_validator(
        "cors_origins", "auth_trusted_proxies", "org_allowlist", "prewarm_orgs", mode="before"
    )
    @classmethod
    def _split_list(cls, value: Any) -> Any:
        """Accept a JSON array or a comma-separated string from the environment."""
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                return json.loads(text)
            return [part.strip() for part in text.split(",") if part.strip()]
        return value

    @field_validator("auth_dev_secret", "auth_jwks_url", mode="before")
    @classmethod
    def _empty_is_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _jwt_mode_is_configured(self) -> Self:
        if self.auth_mode == "jwt":
            missing = [
                name
                for name, value in (
                    ("AUTH_JWKS_URL", self.auth_jwks_url),
                    ("AUTH_JWT_ISSUER", self.auth_jwt_issuer),
                    ("AUTH_JWT_AUDIENCE", self.auth_jwt_audience),
                )
                if not value
            ]
            if missing:
                raise ValueError(f"AUTH_MODE=jwt requires {', '.join(missing)}")
        return self

    @field_validator("github_token", mode="before")
    @classmethod
    def _empty_token_is_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value
