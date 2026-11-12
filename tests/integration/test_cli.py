"""Runs the real entry point in a subprocess, as the container does."""

import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
from importlib.metadata import version
from urllib.parse import urlsplit, urlunsplit

import httpx2
import psycopg
import pytest

from tests.conftest import Database

HEAD = "0004"

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


def test_seed_runs_in_production_when_demo_data_is_allowed(database: Database) -> None:
    result = run(
        "seed",
        MIGRATION_DATABASE_URL=database.owner_url,
        APP_ENV="production",
        SEED_DEMO_DATA="true",
    )
    assert result.returncode == 0, result.stderr


def test_seed_explains_a_missing_url() -> None:
    result = run("seed", MIGRATION_DATABASE_URL="", DATABASE_URL="")
    assert result.returncode == 2
    assert "Set MIGRATION_DATABASE_URL or DATABASE_URL" in result.stderr


def test_prints_the_openapi_document() -> None:
    result = run("openapi", DATABASE_URL="")
    info = json.loads(result.stdout)["info"]
    assert info == {"title": "api-fastapi-starter", "version": version("api-fastapi-starter")}


def test_explains_a_bad_setting_without_echoing_it() -> None:
    result = run("serve", DATABASE_URL="not-a-url-but-a-secret")
    assert result.returncode == 2
    assert "DATABASE_URL" in result.stderr
    assert "not-a-url-but-a-secret" not in result.stderr


def test_healthcheck_fails_when_nothing_listens() -> None:
    assert run("healthcheck", PORT=str(free_port())).returncode == 1


def test_the_image_healthcheck_loads_only_the_standard_library() -> None:
    probe = (
        "import sys, runpy\n"
        "try:\n"
        "    runpy.run_module('app.healthcheck', run_name='__main__')\n"
        "except SystemExit:\n"
        "    pass\n"
        "print(sorted(set(sys.modules) & {'fastapi', 'pydantic', 'sqlalchemy', 'uvicorn', "
        "'alembic', 'opentelemetry', 'app.main', 'app.config'}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "PORT": str(free_port())},
        check=False,
    )
    assert result.stdout.strip() == "[]", result.stderr


def test_concurrent_migrations_wait_for_each_other_and_both_succeed(server_url: str) -> None:
    name = f"api_migrate_{secrets.token_hex(4)}"
    with psycopg.connect(server_url, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = urlunsplit(urlsplit(server_url)._replace(path=f"/{name}"))
    try:
        processes = [
            subprocess.Popen(
                [*COMMAND, "migrate"],
                env={**os.environ, "MIGRATION_DATABASE_URL": url},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(2)
        ]
        for process in processes:
            _, stderr = process.communicate(timeout=120)
            assert process.returncode == 0, stderr
        with psycopg.connect(url) as conn:
            revisions = conn.execute("select version_num from alembic_version").fetchall()
            tables = conn.execute(
                "select count(*) from pg_tables where schemaname = 'public' "
                "and tablename in ('users', 'notes', 'procrastinate_jobs')"
            ).fetchone()
        assert revisions == [(HEAD,)]
        assert tables == (3,)
    finally:
        with psycopg.connect(server_url, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


def test_serves_logs_json_and_shuts_down_cleanly(database: Database) -> None:
    port = free_port()
    env = {
        **os.environ,
        "DATABASE_URL": database.app_url,
        "PORT": str(port),
        "SHUTDOWN_DRAIN_SECONDS": "0",
    }
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
        assert httpx2.get(f"http://127.0.0.1:{port}/v1/notes").status_code == 401
    finally:
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=30)
    assert "Application shutdown complete." in stdout + stderr
    entries = [json.loads(line) for line in stdout.splitlines() if line.startswith("{")]
    assert any(entry.get("msg") == "Request completed" for entry in entries)
    assert all("color_message" not in entry for entry in entries)


def test_drains_on_sigterm_failing_readiness_while_still_serving(database: Database) -> None:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "DATABASE_URL": database.app_url,
        "PORT": str(port),
        "SHUTDOWN_DRAIN_SECONDS": "3",
    }
    process = subprocess.Popen(
        [*COMMAND, "serve"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        wait_until_ready(base)
        process.send_signal(signal.SIGTERM)
        time.sleep(0.5)
        with httpx2.Client(base_url=base, timeout=5) as http:
            ready = http.get("/readyz")
            live = http.get("/healthz")
            served = http.get("/v1/notes")
        assert process.poll() is None, "the API stopped before the drain ended"
        started = time.monotonic()
        process.wait(timeout=30)
        assert time.monotonic() - started >= 1.5
    finally:
        process.kill()
        stdout, _ = process.communicate(timeout=30)
    assert ready.status_code == 503
    assert "shutting down" in ready.json()["detail"]
    assert (live.status_code, served.status_code) == (200, 401)
    assert '"msg": "Draining before shutdown"' in stdout


def wait_until_ready(base: str) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if httpx2.get(f"{base}/readyz").status_code == 200:
                return
        except httpx2.TransportError:
            time.sleep(0.1)
    pytest.fail(f"{base} never became ready")


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
