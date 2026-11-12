"""Settings from environment variables, validated once at startup."""

import os
from typing import Literal, Self

from pydantic import Field, PostgresDsn, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["debug", "info", "warn", "warning", "error"]


class ConfigError(Exception):
    """A setting is missing or invalid. The message names the variable, never its value."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False, env_ignore_empty=True)

    database_url: PostgresDsn
    port: int = Field(default=3000, ge=1, le=65535)
    log_level: LogLevel = "info"
    database_statement_timeout_ms: int = Field(default=5000, ge=100, le=600_000)
    database_pool_max: int = Field(default=10, ge=1)
    cors_origins: str = ""
    trust_proxy_hops: int = Field(default=0, ge=0)
    session_ttl_hours: int = Field(default=168, ge=1, le=9600)
    rate_limit_per_minute: int = Field(default=300, ge=1)
    auth_rate_limit_per_minute: int = Field(default=10, ge=1)
    login_failure_limit: int = Field(default=5, ge=1)
    login_failure_window_seconds: int = Field(default=900, ge=1)
    shutdown_drain_seconds: int = Field(default=5, ge=0)
    shutdown_timeout_seconds: int = Field(default=30, ge=1)
    keep_alive_timeout_seconds: int = Field(default=75, ge=1)
    docs_enabled: bool = False

    @model_validator(mode="after")
    def _outlast_the_slowest_query(self) -> Self:
        if self.shutdown_timeout_seconds * 1000 < self.database_statement_timeout_ms:
            raise ValueError(
                "SHUTDOWN_TIMEOUT_SECONDS must be at least DATABASE_STATEMENT_TIMEOUT_MS, "
                "so in-flight requests can finish"
            )
        return self

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


class SeedSettings(BaseSettings):
    """What `seed` reads. It runs before the API, often with only the owner role's URL."""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False, env_ignore_empty=True)

    migration_database_url: PostgresDsn | None = None
    database_url: PostgresDsn | None = None
    app_env: str = ""
    seed_demo_data: bool = False


def database_url(url: str) -> str:
    """Points a postgres:// URL at the psycopg driver, which both SQLAlchemy and the queue use."""
    for prefix in ("postgresql+psycopg://", "postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url


def load_settings(env: dict[str, str] | None = None) -> Settings:
    source = os.environ if env is None else env
    if any(key.upper() == "TRUST_PROXY" and value for key, value in source.items()):
        raise ConfigError(
            "TRUST_PROXY was replaced by TRUST_PROXY_HOPS. Set TRUST_PROXY_HOPS=1 for the old behavior."
        )
    return _load(Settings, env)


def load_seed_settings(env: dict[str, str] | None = None) -> SeedSettings:
    return _load(SeedSettings, env)


def _load[T: BaseSettings](model: type[T], env: dict[str, str] | None) -> T:
    try:
        if env is None:
            return model()
        return model.model_validate({key.lower(): value for key, value in env.items() if value})
    except ValidationError as error:
        fields = [
            ": ".join(
                part
                for part in (".".join(str(loc) for loc in issue["loc"]).upper(), issue["msg"])
                if part
            )
            for issue in error.errors(include_input=False, include_url=False)
        ]
        raise ConfigError(f"Invalid environment: {'; '.join(fields)}") from None
