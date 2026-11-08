import asyncio
import json
import logging
import secrets
from collections.abc import AsyncIterator

import httpx2
import psycopg
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import database_url
from app.main import create_app
from tests.conftest import ROOT, Database
from tests.helpers import PASSWORD, api, assert_problem, settings

pytestmark = pytest.mark.anyio


def ip() -> str:
    return f"203.0.113.{secrets.randbelow(250) + 1}-{secrets.token_hex(3)}"


async def test_rate_limit_blocks_login_after_the_auth_limit_with_retry_after(
    database: Database,
) -> None:
    async with api(database, AUTH_RATE_LIMIT_PER_MINUTE="2", TRUST_PROXY="true") as client:
        headers = {"X-Forwarded-For": ip()}
        body = {"email": "nobody@example.com", "password": PASSWORD}
        statuses = [
            (await client.http.post("/v1/sessions", json=body, headers=headers)).status_code
            for _ in range(3)
        ]
        blocked = await client.http.post("/v1/sessions", json=body, headers=headers)
    assert statuses == [401, 401, 429]
    assert_problem(blocked, 429, "rate-limited")
    assert 1 <= int(blocked.headers["retry-after"]) <= 60


async def test_rate_limit_applies_the_global_limit_to_every_v1_route(database: Database) -> None:
    async with api(database, RATE_LIMIT_PER_MINUTE="2", TRUST_PROXY="true") as client:
        headers = {"X-Forwarded-For": ip()}
        statuses = [
            (await client.http.get(path, headers=headers)).status_code
            for path in ("/v1/notes", "/v1/users/me", "/v1/notes/x")
        ]
    assert statuses == [401, 401, 429]


async def test_rate_limit_reports_the_remaining_budget(database: Database) -> None:
    async with api(database, RATE_LIMIT_PER_MINUTE="5", TRUST_PROXY="true") as client:
        response = await client.http.get("/v1/notes", headers={"X-Forwarded-For": ip()})
    assert (response.headers["ratelimit-limit"], response.headers["ratelimit-remaining"]) == (
        "5",
        "4",
    )
    assert 1 <= int(response.headers["ratelimit-reset"]) <= 60


async def test_rate_limit_counts_concurrent_requests_exactly(database: Database) -> None:
    async with api(database, RATE_LIMIT_PER_MINUTE="10", TRUST_PROXY="true") as client:
        headers = {"X-Forwarded-For": ip()}
        responses = await asyncio.gather(
            *(client.http.get("/v1/notes", headers=headers) for _ in range(15))
        )
    assert sorted(response.status_code for response in responses).count(429) == 5


async def test_rate_limit_starts_a_new_window_once_the_old_one_ends(
    database: Database, owner: psycopg.AsyncConnection
) -> None:
    client_ip = ip()
    async with api(database, RATE_LIMIT_PER_MINUTE="1", TRUST_PROXY="true") as client:
        headers = {"X-Forwarded-For": client_ip}
        await client.http.get("/v1/notes", headers=headers)
        assert (await client.http.get("/v1/notes", headers=headers)).status_code == 429
        await owner.execute(
            "update rate_limits set reset_at = now() - interval '1 second' where key = %s",
            [f"global:{client_ip}"],
        )
        assert (await client.http.get("/v1/notes", headers=headers)).status_code == 401


async def test_rate_limit_never_limits_health_checks(database: Database) -> None:
    async with api(database, RATE_LIMIT_PER_MINUTE="1") as client:
        statuses = {(await client.http.get("/healthz")).status_code for _ in range(5)}
    assert statuses == {200}


async def test_returns_problem_details_for_an_unknown_route(database: Database) -> None:
    async with api(database) as client:
        response = await client.http.get("/v1/nothing-here")
    body = assert_problem(response, 404, "not-found")
    assert body["instance"] == "/v1/nothing-here"


async def test_rejects_an_unsupported_method(database: Database) -> None:
    async with api(database) as client:
        response = await client.http.put("/v1/notes", json={})
    assert_problem(response, 405, "method-not-allowed")


async def test_rejects_malformed_json(database: Database) -> None:
    async with api(database) as client:
        response = await client.http.post(
            "/v1/users", content=b'{"email":', headers={"Content-Type": "application/json"}
        )
    body = assert_problem(response, 400, "validation-failed")
    assert body["errors"] == [{"field": "body", "detail": "isn't valid JSON"}]


@pytest.mark.parametrize("chunked", [False, True])
async def test_rejects_an_oversized_body(database: Database, chunked: bool) -> None:
    payload = json.dumps({"email": "a@example.com", "password": "x" * 200_000}).encode()

    async def stream() -> AsyncIterator[bytes]:
        yield payload

    async with api(database) as client:
        response = await client.http.post(
            "/v1/users",
            content=stream() if chunked else payload,
            headers={"Content-Type": "application/json"},
        )
    assert_problem(response, 413, "payload-too-large")


@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded"])
async def test_rejects_a_body_that_is_not_json_with_415(
    database: Database, content_type: str
) -> None:
    async with api(database) as client:
        response = await client.http.post(
            "/v1/users", content=b"email=a", headers={"Content-Type": content_type}
        )
    assert_problem(response, 415, "unsupported-media-type")


async def test_answers_head_like_get_without_a_body(database: Database) -> None:
    async with api(database) as client:
        response = await client.http.head("/healthz")
    assert (response.status_code, response.content) == (200, b"")


async def test_hides_internals_and_logs_the_real_error(
    database: Database, caplog: pytest.LogCaptureFixture
) -> None:
    broken = create_async_engine(
        database_url("postgresql://nobody:wrong@127.0.0.1:1/none"),
        connect_args={"connect_timeout": 1},
    )
    app = create_app(settings(database), engine=broken)
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        with caplog.at_level(logging.ERROR, logger="app.http"):
            response = await http.get("/v1/users/me", headers={"Authorization": "Bearer x"})
    body = assert_problem(response, 500, "internal-error")
    request_id = response.headers["x-request-id"]
    assert request_id in body["detail"]
    assert "nobody" not in response.text
    assert any(
        record.message == "Unhandled error" and getattr(record, "requestId", "") == request_id
        for record in caplog.records
    )
    await broken.dispose()


async def test_sets_security_headers_and_a_request_id(database: Database) -> None:
    async with api(database) as client:
        response = await client.http.get("/healthz")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert len(response.headers["x-request-id"]) == 32


async def test_cors_allows_a_listed_origin_and_answers_a_preflight(database: Database) -> None:
    origin = "https://app.example.com"
    async with api(database, CORS_ORIGINS=origin) as client:
        simple = await client.http.get("/v1/notes", headers={"Origin": origin})
        preflight = await client.http.options(
            "/v1/notes",
            headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
        )
        other = await client.http.get("/v1/notes", headers={"Origin": "https://evil.example"})
    assert simple.headers["access-control-allow-origin"] == origin
    assert preflight.status_code == 204
    assert "Idempotency-Key" in preflight.headers["access-control-allow-headers"]
    assert "access-control-allow-origin" not in other.headers


async def test_cors_sends_no_headers_by_default(database: Database) -> None:
    async with api(database) as client:
        response = await client.http.get("/v1/notes", headers={"Origin": "https://app.example.com"})
    assert "access-control-allow-origin" not in response.headers


async def test_reports_health_and_readiness(database: Database) -> None:
    async with api(database) as client:
        assert (await client.http.get("/healthz")).json() == {"status": "ok"}
        assert (await client.http.get("/readyz")).json() == {"status": "ok"}


async def test_reports_unready_when_postgres_is_down(database: Database) -> None:
    broken = create_async_engine(
        database_url("postgresql://nobody:wrong@127.0.0.1:1/none"),
        connect_args={"connect_timeout": 1},
    )
    app = create_app(settings(database), engine=broken)
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        response = await http.get("/readyz")
        live = await http.get("/healthz")
    assert_problem(response, 503, "service-unavailable")
    assert response.headers["retry-after"] == "5"
    assert live.status_code == 200
    await broken.dispose()


async def test_logs_each_request_as_json_without_credentials(
    database: Database, caplog: pytest.LogCaptureFixture
) -> None:
    async with api(database) as client:
        with caplog.at_level(logging.INFO, logger="app.http"):
            user = await client.sign_up()
            await user.request("GET", "/v1/users/me")
    records = [record for record in caplog.records if record.message == "Request completed"]
    assert {"/v1/users", "/v1/sessions", "/v1/users/me"} <= {
        getattr(r, "path", "") for r in records
    }
    assert all(getattr(r, "requestId", "") and getattr(r, "durationMs", -1) >= 0 for r in records)
    assert PASSWORD not in caplog.text
    assert user.token not in caplog.text


async def test_serves_an_openapi_document_that_matches_the_committed_one(
    database: Database,
) -> None:
    async with api(database) as client:
        served = (await client.http.get("/openapi.json")).json()
        docs = await client.http.get("/docs")
    committed = json.loads((ROOT / "openapi.json").read_text())
    assert served == committed, "openapi.json is stale. Run make openapi and commit it"
    assert docs.status_code == 200
    responses = served["paths"]["/v1/notes"]["post"]["responses"]
    assert "422" not in responses
    assert "400" in responses
