"""Runs the Compose stack from the real images, and drives it from the outside."""

import json
import os
import secrets
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx2
import pytest
from api_client import AuthenticatedClient, Client
from api_client.api.auth import create_session, create_user
from api_client.api.notes import create_note, delete_note, list_notes, update_note
from api_client.models import (
    CreateNote,
    CreateSession,
    CreateSessionDelivery,
    Credentials,
    UpdateNote,
)

ROOT = Path(__file__).parents[2]
PROJECT = "api-fastapi-starter-e2e"
PORT, DB_PORT, OTLP_PORT = "3160", "5560", "4340"
BASE = f"http://127.0.0.1:{PORT}"


class Collector(BaseHTTPRequestHandler):
    traces = bytearray()
    lock = threading.Lock()

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        if self.path == "/v1/traces":
            with self.lock:
                Collector.traces += body
        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


def traced(text: str) -> bool:
    with Collector.lock:
        return text.encode() in Collector.traces


def compose(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["docker", "compose", "-f", str(ROOT / "compose.yaml"), *args],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "COMPOSE_PROJECT_NAME": PROJECT,
            "PORT": PORT,
            "POSTGRES_PORT": DB_PORT,
            "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://host.docker.internal:{OTLP_PORT}",
        },
    )
    if check and result.returncode != 0:
        pytest.fail(f"docker compose {' '.join(args)}:\n{result.stdout}\n{result.stderr}")
    return result.stdout + result.stderr


def wait_for(check: Callable[[], bool], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.25)
    pytest.fail(f"timed out after {timeout}s")


def status(path: str) -> int:
    try:
        with httpx2.Client(timeout=5) as http:
            return http.get(BASE + path).status_code
    except httpx2.TransportError:
        return 0


@pytest.fixture(scope="module", autouse=True)
def stack() -> Iterator[None]:
    server = ThreadingHTTPServer(("0.0.0.0", int(OTLP_PORT)), Collector)  # noqa: S104 - containers reach it
    threading.Thread(target=server.serve_forever, daemon=True).start()
    compose("down", "--volumes", "--remove-orphans", check=False)
    compose("up", "--build", "--detach", "--wait", "api", "worker")
    try:
        yield
    finally:
        compose("down", "--volumes", "--remove-orphans", check=False)
        server.shutdown()
        server.server_close()


def token(email: str, password: str) -> str:
    with Client(base_url=BASE) as anonymous:
        session = create_session.sync(
            client=anonymous, body=CreateSession(email=email, password=password)
        )
    assert session is not None
    assert isinstance(getattr(session, "token", None), str), session
    value: str = session.token
    return value


def register(email: str) -> int:
    with Client(base_url=BASE) as anonymous:
        response = create_user.sync_detailed(
            client=anonymous, body=Credentials(email=email, password="correct-horse-battery")
        )
    code: int = response.status_code
    return code


def test_is_ready_healthy_and_non_root() -> None:
    assert status("/readyz") == 200
    state = json.loads(compose("ps", "api", "--format", "json"))
    assert state["Health"] == "healthy"
    user = subprocess.run(
        ["docker", "exec", f"{PROJECT}-api-1", "id", "-u"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert user.stdout.strip() == "10001"


def test_logs_in_with_the_seeded_demo_user_and_reads_fake_notes() -> None:
    with AuthenticatedClient(
        base_url=BASE, token=token("demo@example.com", "demo-password-123")
    ) as client:
        page = list_notes.sync(client=client)
    assert page is not None
    assert hasattr(page, "data")
    assert len(page.data) == 2


def test_runs_the_whole_note_lifecycle_through_the_generated_client() -> None:
    email = f"e2e-{secrets.token_hex(4)}@example.com"
    assert register(email) == 201
    with AuthenticatedClient(base_url=BASE, token=token(email, "correct-horse-battery")) as client:
        note = create_note.sync(client=client, body=CreateNote(title="From the outside"))
        assert note is not None
        assert hasattr(note, "id")
        updated = update_note.sync(
            note_id=note.id, client=client, body=UpdateNote(title="Changed"), if_match='"1"'
        )
        assert updated is not None
        assert getattr(updated, "version", None) == 2
        assert delete_note.sync_detailed(note_id=note.id, client=client).status_code == 204


def test_logs_in_with_a_session_cookie_and_logs_out() -> None:
    with Client(base_url=BASE) as anonymous:
        login = create_session.sync_detailed(
            client=anonymous,
            body=CreateSession(
                email="demo@example.com",
                password="demo-password-123",
                delivery=CreateSessionDelivery.COOKIE,
            ),
        )
    assert login.status_code == 201
    assert "token" not in json.loads(login.content)
    set_cookie = login.headers["set-cookie"]
    assert {"HttpOnly", "Secure", "SameSite=strict", "Path=/"} <= {
        part.strip() for part in set_cookie.split(";")
    }
    cookie = {"Cookie": set_cookie.split(";")[0]}
    cross_site = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
    with httpx2.Client(base_url=BASE, timeout=5) as http:
        assert http.get("/v1/users/me", headers=cookie).json()["email"] == "demo@example.com"
        forged = http.post("/v1/notes", json={"title": "Forged"}, headers=cookie | cross_site)
        assert forged.status_code == 403
        assert "urn:problem:forbidden" in forged.text
        logout = http.delete("/v1/sessions/current", headers=cookie)
        assert logout.status_code == 204
        assert "Max-Age=0" in logout.headers["set-cookie"]
        assert http.get("/v1/users/me", headers=cookie).status_code == 401


def test_the_worker_sends_the_welcome_email() -> None:
    email = f"welcome-{secrets.token_hex(4)}@example.com"
    assert register(email) == 201
    wait_for(lambda: "Email not sent" in compose("logs", "--no-log-prefix", "worker"), 30)


def test_writes_structured_json_logs_without_credentials() -> None:
    logs = compose("logs", "--no-log-prefix", "api")
    assert "demo-password-123" not in logs
    assert "Bearer" not in logs
    entries = [json.loads(line) for line in logs.splitlines() if line.startswith("{")]
    assert any(
        entry.get("msg") == "Request completed" and entry.get("requestId") for entry in entries
    )


def test_exports_route_named_spans_with_database_spans() -> None:
    wait_for(lambda: traced("GET /v1/notes") and traced("api-fastapi-starter"), 30)
    wait_for(lambda: traced("SELECT"), 30)


def test_reports_a_database_outage_records_the_error_and_recovers() -> None:
    compose("stop", "db")
    try:
        assert status("/healthz") == 200
        assert status("/readyz") == 503
        with httpx2.Client(timeout=15) as http:
            response = http.get(BASE + "/v1/notes")
        assert response.status_code == 500
        assert "urn:problem:internal-error" in response.text
        assert "api_app" not in response.text
        wait_for(lambda: traced("exception"), 30)
    finally:
        compose("start", "db")
    wait_for(lambda: status("/readyz") == 200, 60)


def test_keeps_data_across_a_restart() -> None:
    compose("restart", "api")
    wait_for(lambda: status("/readyz") == 200, 60)
    assert token("demo@example.com", "demo-password-123")


def test_shuts_down_gracefully_on_sigterm() -> None:
    compose("stop", "api")
    logs = compose("logs", "--no-log-prefix", "api")
    assert "Application shutdown complete." in logs
    code = compose("ps", "--all", "api", "--format", "{{.ExitCode}}").strip().splitlines()[-1]
    assert code in {"0", "143"}, code
