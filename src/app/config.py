"""Settings from environment variables, validated once at startup."""

from typing import Literal

from pydantic import Field, PostgresDsn, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    """A setting is missing or invalid. The message names the variable, never its value."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False, env_ignore_empty=True)

    database_url: PostgresDsn
    port: int = Field(default=3000, ge=1, le=65535)
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    database_statement_timeout_ms: int = Field(default=5000, ge=100, le=600_000)
    cors_origins: str = ""
    trust_proxy: bool = False
    session_ttl_hours: int = Field(default=168, ge=1, le=8760)
    rate_limit_per_minute: int = Field(default=300, ge=1)
    auth_rate_limit_per_minute: int = Field(default=10, ge=1)
    app_env: str = ""

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


def database_url(url: str) -> str:
    """Points a postgres:// URL at the psycopg driver, which both SQLAlchemy and the queue use."""
    for prefix in ("postgresql+psycopg://", "postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url


def load_settings(env: dict[str, str] | None = None) -> Settings:
    try:
        if env is None:
            return Settings()
        return Settings.model_validate({key.lower(): value for key, value in env.items() if value})
    except ValidationError as error:
        fields = [
            f"{'.'.join(str(part) for part in issue['loc']).upper()}: {issue['msg']}"
            for issue in error.errors(include_input=False, include_url=False)
        ]
        raise ConfigError(f"Invalid environment: {'; '.join(fields)}") from None
