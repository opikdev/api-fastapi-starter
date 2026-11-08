"""Runs the real entry point in a subprocess, as the container does."""

import json
import os
import signal
import socket
import subprocess
import sys
import time

import httpx2
import psycopg
import pytest

from tests.conftest import Database

COMMAND = [sys.executable, "-m", "app"]


def run(*args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*COMMAND, *args],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, **env},
        check=False,
    )


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def test_migrate_is_safe_to_rerun(database: Database) -> None:
    result = run("migrate", MIGRATION_DATABASE_URL=database.owner_url)
    assert result.returncode == 0, result.stderr
    assert "Migrations applied" in result.stdout


def test_migrate_explains_a_missing_url() -> None:
    result = run("migrate", MIGRATION_DATABASE_URL="")
    assert result.returncode == 2
    assert "Set MIGRATION_DATABASE_URL" in result.stderr


@pytest.mark.anyio
async def test_seed_adds_the_demo_user_once(
    database: Database, owner: psycopg.AsyncConnection
) -> None:
    await owner.execute("delete from users where email = 'demo@example.com'")
    first = run("seed", MIGRATION_DATABASE_URL=database.owner_url)
    second = run("seed", MIGRATION_DATABASE_URL=database.owner_url)
    assert "Seeded demo@example.com" in first.stdout, first.stderr
    assert "already exists" in second.stdout
    notes = await (
        await owner.execute(
            "select count(*) from notes join users on users.id = notes.user_id "
            "where users.email = 'demo@example.com'"
        )
    ).fetchone()
    assert notes == (2,)


def test_seed_refuses_to_run_in_production(database: Database) -> None:
    result = run("seed", MIGRATION_DATABASE_URL=database.owner_url, APP_ENV="production")
    assert result.returncode == 2
    assert "Refusing to seed" in result.stderr


def test_prints_the_openapi_document() -> None:
    result = run("openapi", DATABASE_URL="")
    assert json.loads(result.stdout)["info"]["title"] == "API FastAPI starter"


def test_explains_a_bad_setting_without_echoing_it() -> None:
    result = run("serve", DATABASE_URL="not-a-url-but-a-secret")
    assert result.returncode == 2
    assert "DATABASE_URL" in result.stderr
    assert "not-a-url-but-a-secret" not in result.stderr


def test_healthcheck_fails_when_nothing_listens() -> None:
    assert run("healthcheck", PORT=str(free_port())).returncode == 1


def test_serves_logs_json_and_shuts_down_cleanly(database: Database) -> None:
    port = free_port()
    env = {**os.environ, "DATABASE_URL": database.app_url, "PORT": str(port)}
    process = subprocess.Popen(
        [*COMMAND, "serve"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if httpx2.get(f"http://127.0.0.1:{port}/readyz").status_code == 200:
                    break
            except httpx2.TransportError:
                time.sleep(0.1)
        assert run("healthcheck", PORT=str(port)).returncode == 0
    finally:
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=30)
    assert "Application shutdown complete." in stdout + stderr
    entries = [json.loads(line) for line in stdout.splitlines() if line.startswith("{")]
    assert any(entry.get("msg") == "Request completed" for entry in entries)


def test_worker_starts_and_stops_on_sigterm(database: Database) -> None:
    env = {**os.environ, "DATABASE_URL": database.app_url}
    process = subprocess.Popen(
        [*COMMAND, "worker"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    time.sleep(3)
    process.send_signal(signal.SIGTERM)
    _, stderr = process.communicate(timeout=30)
    assert process.returncode == 0, stderr
    assert "Traceback" not in stderr
