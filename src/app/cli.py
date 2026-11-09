"""The single entry point: serve, migrate, seed, worker, healthcheck, and openapi."""

import argparse
import asyncio
import json
import os
import sys
import urllib.request
from importlib.resources import files

import uvicorn
from alembic import command
from alembic.config import Config

from app import jobs
from app.config import ConfigError, load_seed_settings, load_settings
from app.db import create_engine
from app.log import configure_logging
from app.main import create_app
from app.seed import DEMO_EMAIL, DEMO_PASSWORD, seed

COMMANDS = {
    "serve": "Serve the API (the default)",
    "migrate": "Apply migrations, using MIGRATION_DATABASE_URL",
    "seed": "Add fake demo data, using MIGRATION_DATABASE_URL or DATABASE_URL",
    "worker": "Run background jobs, using DATABASE_URL",
    "healthcheck": "Exit 0 if GET /healthz on PORT succeeds",
    "openapi": "Print the OpenAPI document",
}


def _serve() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    uvicorn.run(
        create_app(settings),
        host="0.0.0.0",  # noqa: S104 - the container needs it, and Compose binds the port to localhost
        port=settings.port,
        log_config=None,
        access_log=False,
        proxy_headers=False,
        timeout_graceful_shutdown=10,
    )


def _migrate() -> None:
    url = os.environ.get("MIGRATION_DATABASE_URL")
    if not url:
        raise ConfigError("Set MIGRATION_DATABASE_URL to the owner role's connection.")
    config = Config()
    config.set_main_option("script_location", str(files("app") / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    print("Migrations applied")


def _seed() -> None:
    settings = load_seed_settings()
    if settings.app_env == "production" and not settings.seed_demo_data:
        raise ConfigError("Refusing to seed: APP_ENV is production and SEED_DEMO_DATA is not true.")
    url = settings.migration_database_url or settings.database_url
    if url is None:
        raise ConfigError("Set MIGRATION_DATABASE_URL or DATABASE_URL.")

    async def run() -> bool:
        engine = create_engine(str(url))
        try:
            return await seed(engine)
        finally:
            await engine.dispose()

    if asyncio.run(run()):
        print(f"Seeded {DEMO_EMAIL} with password {DEMO_PASSWORD}")
    else:
        print(f"{DEMO_EMAIL} already exists, so nothing was seeded")


def _worker() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)

    asyncio.run(jobs.run_worker(settings, install_signal_handlers=True))


def _healthcheck() -> None:
    port = int(os.environ.get("PORT", "3000"))
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as response:
            ok = response.status == 200
    except OSError:
        ok = False
    sys.exit(0 if ok else 1)


def _openapi() -> None:
    # The document doesn't need a database, so a placeholder URL is enough.
    if not os.environ.get("DATABASE_URL"):
        os.environ["DATABASE_URL"] = "postgresql://unused@localhost/unused"
    app = create_app(load_settings())
    print(json.dumps(app.openapi(), indent=2))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="api-fastapi-starter",
        description="\n".join(f"  {name:<12} {text}" for name, text in COMMANDS.items()),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", nargs="?", default="serve", choices=COMMANDS)
    args = parser.parse_args(argv)
    actions = {
        "serve": _serve,
        "migrate": _migrate,
        "seed": _seed,
        "worker": _worker,
        "healthcheck": _healthcheck,
        "openapi": _openapi,
    }
    try:
        actions[args.command]()
    except ConfigError as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(2)
