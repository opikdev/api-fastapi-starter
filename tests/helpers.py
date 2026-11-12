"""An API client over the real ASGI app, with helpers to sign up and log in."""

import contextlib
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx2
from fastapi import FastAPI
from procrastinate.testing import InMemoryConnector

from app import jobs
from app.config import Settings, load_settings
from app.main import create_app
from tests.conftest import Database

PASSWORD = "correct-horse-battery"


@dataclass
class Api:
    http: httpx2.AsyncClient
    jobs: InMemoryConnector
    app: FastAPI

    async def sign_up(self, email: str | None = None) -> User:
        email = email or f"user-{secrets.token_hex(6)}@example.com"
        created = await self.http.post("/v1/users", json={"email": email, "password": PASSWORD})
        assert created.status_code == 201, created.text
        login = await self.http.post("/v1/sessions", json={"email": email, "password": PASSWORD})
        assert login.status_code == 201, login.text
        return User(self, email, created.json()["id"], login.json()["token"])


@dataclass
class User:
    api: Api
    email: str
    id: str
    token: str

    @property
    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx2.Response:
        headers = {**self.auth, **kwargs.pop("headers", {})}
        return await self.api.http.request(method, path, headers=headers, **kwargs)

    async def create_note(self, title: str = "A note", body: str = "") -> dict[str, Any]:
        response = await self.request("POST", "/v1/notes", json={"title": title, "body": body})
        assert response.status_code == 201, response.text
        note: dict[str, Any] = response.json()
        return note


def settings(database: Database, **overrides: str) -> Settings:
    env = {
        "DATABASE_URL": database.app_url,
        "RATE_LIMIT_PER_MINUTE": "100000",
        "AUTH_RATE_LIMIT_PER_MINUTE": "100000",
        "LOGIN_FAILURE_LIMIT": "100000",
        "DOCS_ENABLED": "true",
        **overrides,
    }
    return load_settings(env)


@contextlib.asynccontextmanager
async def api(
    database: Database, connector: InMemoryConnector | None = None, **overrides: str
) -> AsyncIterator[Api]:
    """Runs the app with its lifespan, and an in-memory queue that records deferred jobs."""
    app = create_app(settings(database, **overrides))
    connector = connector or InMemoryConnector()
    with jobs.queue.replace_connector(connector):
        async with (
            app.router.lifespan_context(app),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
            ) as http,
        ):
            yield Api(http, connector, app)


def assert_problem(response: httpx2.Response, status: int, slug: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/problem+json"
    body: dict[str, Any] = response.json()
    assert body["type"] == f"urn:problem:{slug}"
    assert body["status"] == status
    return body


def assert_field_error(response: httpx2.Response, field: str) -> None:
    fields = [error["field"] for error in response.json().get("errors", [])]
    assert field in fields, response.text
