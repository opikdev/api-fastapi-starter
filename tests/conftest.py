"""A real Postgres 18 per test run: Testcontainers, or TEST_DATABASE_URL when Docker isn't there."""

import os
import secrets
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).parents[1]
APP_PASSWORD = "api_app_dev_password"


@dataclass(frozen=True)
class Database:
    owner_url: str
    app_url: str
    name: str


def _with_database(
    url: str, name: str, user: str | None = None, password: str | None = None
) -> str:
    parts = urlsplit(url)
    netloc = parts.netloc
    if user is not None:
        netloc = f"{user}:{password}@{parts.hostname}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, f"/{name}", parts.query, ""))


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def server_url() -> Iterator[str]:
    if url := os.environ.get("TEST_DATABASE_URL"):
        yield url
        return
    # Imported here, so a run with TEST_DATABASE_URL works without Docker.
    from testcontainers.community.postgres import PostgresContainer  # noqa: PLC0415

    with PostgresContainer("postgres:18-alpine", driver=None) as container:
        yield container.get_connection_url()


@pytest.fixture(scope="session")
def database(server_url: str) -> Iterator[Database]:
    """A temporary database with the roles from init.sql, migrated by the owner role."""
    name = f"api_test_{secrets.token_hex(4)}"
    with psycopg.connect(server_url, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    owner_url = _with_database(server_url, name)
    with psycopg.connect(owner_url, autocommit=True) as owner:
        owner.execute((ROOT / "docker/postgres/init.sql").read_text())
        owner.execute(f"ALTER ROLE api_app PASSWORD '{APP_PASSWORD}'")

    config = Config()
    config.set_main_option("script_location", str(ROOT / "src/app/migrations"))
    config.set_main_option("sqlalchemy.url", owner_url)
    command.upgrade(config, "head")

    app_url = _with_database(server_url, name, "api_app", APP_PASSWORD)
    try:
        yield Database(owner_url=owner_url, app_url=app_url, name=name)
    finally:
        with psycopg.connect(server_url, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


@pytest.fixture
async def owner(database: Database) -> AsyncIterator[psycopg.AsyncConnection]:
    """A connection as the owner role, to inspect or arrange rows behind the API's back."""
    async with await psycopg.AsyncConnection.connect(database.owner_url, autocommit=True) as conn:
        yield conn
