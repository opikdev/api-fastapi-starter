"""The single entry point: serve, migrate, seed, worker, healthcheck, and openapi."""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from importlib.resources import files
from types import FrameType

import uvicorn
from alembic import command
from alembic.config import Config
from fastapi import FastAPI

from app import healthcheck, jobs
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


logger = logging.getLogger("app.cli")


class DrainingServer(uvicorn.Server):
    """On the first SIGTERM or SIGINT, fails readiness but keeps serving, then shuts down.

    The drain gives load balancers time to stop sending requests before connections close.
    A second signal skips the rest of the drain.
    """

    def __init__(self, config: uvicorn.Config, app: FastAPI, drain_seconds: int) -> None:
        super().__init__(config)
        self.app = app
        self.drain_seconds = drain_seconds
        self.drain_until: float | None = None
        self.pending_exit: tuple[int, FrameType | None] | None = None
        self.announced = False

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        if self.drain_until is None:
            self.app.state.draining = True
            self.drain_until = time.monotonic() + self.drain_seconds
            self.pending_exit = (sig, frame)
            return
        super().handle_exit(sig, frame)

    async def on_tick(self, counter: int) -> bool:
        if self.drain_until is not None and not self.announced:
            # Logged here, not in the signal handler, which may interrupt another log call.
            logger.info("Draining before shutdown", extra={"seconds": self.drain_seconds})
            self.announced = True
        if self.pending_exit and time.monotonic() >= (self.drain_until or 0):
            super().handle_exit(*self.pending_exit)
            self.pending_exit = None
        return await super().on_tick(counter)


def _serve() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    app = create_app(settings)
    config = uvicorn.Config(
        app,
        host="0.0.0.0",  # noqa: S104 - the container needs it, and Compose binds the port to localhost
        port=settings.port,
        log_config=None,
        access_log=False,
        proxy_headers=False,
        timeout_keep_alive=settings.keep_alive_timeout_seconds,
        timeout_graceful_shutdown=settings.shutdown_timeout_seconds,
    )
    DrainingServer(config, app, settings.shutdown_drain_seconds).run()


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
        "healthcheck": healthcheck.main,
        "openapi": _openapi,
    }
    try:
        actions[args.command]()
    except ConfigError as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(2)
