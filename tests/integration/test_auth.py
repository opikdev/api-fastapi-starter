import asyncio
import secrets
import threading
from datetime import UTC, datetime

import httpx2
import psycopg
import pytest

from app import security
from app.features.auth import routes
from tests.conftest import Database
from tests.helpers import PASSWORD, Api, api, assert_field_error, assert_problem

pytestmark = pytest.mark.anyio


def email() -> str:
    return f"user-{secrets.token_hex(6)}@example.com"


async def cookie_login(client: Api, address: str) -> httpx2.Response:
    return await client.http.post(
        "/v1/sessions", json={"email": address, "password": PASSWORD, "delivery": "cookie"}
    )


def session_cookie(response: httpx2.Response) -> dict[str, str]:
    name, value = response.headers["set-cookie"].split(";")[0].split("=", 1)
    assert name == "__Host-session"
    return {"Cookie": f"__Host-session={value}"}


def assert_clears_the_cookie(response: httpx2.Response) -> None:
    attributes = [part.strip().lower() for part in response.headers["set-cookie"].split(";")]
    assert attributes[0] in {"__host-session=", '__host-session=""'}
    assert {"max-age=0", "path=/", "httponly", "secure", "samesite=strict"} <= set(attributes)


async def test_registration_creates_a_user_and_hides_the_password(
    database: Database, owner: psycopg.AsyncConnection
) -> None:
    address = email()
    async with api(database) as client:
        response = await client.http.post(
            "/v1/users", json={"email": address, "password": PASSWORD}
        )
        assert response.status_code == 201
        body = response.json()
        assert set(body) == {"id", "email", "createdAt"}
        assert body["id"].startswith("usr_")
        assert client.jobs.jobs, "registration should queue a welcome email"
        job = next(iter(client.jobs.jobs.values()))
        assert job["task_name"] == "send_welcome_email"
    row = await (
        await owner.execute("select password_hash from users where email = %s", [address])
    ).fetchone()
    assert row is not None
    assert row[0].startswith("$argon2id$")
    assert PASSWORD not in row[0]


async def test_registration_lowercases_the_email_and_treats_case_variants_as_one_user(
    database: Database,
) -> None:
    address = email()
    async with api(database) as client:
        first = await client.http.post(
            "/v1/users", json={"email": address.upper(), "password": PASSWORD}
        )
        assert first.json()["email"] == address
        again = await client.http.post("/v1/users", json={"email": address, "password": PASSWORD})
        assert_problem(again, 409, "email-taken")


@pytest.mark.parametrize(
    ("label", "body", "field"),
    [
        ("a short password", {"email": "a@example.com", "password": "short"}, "password"),
        ("a long password", {"email": "a@example.com", "password": "x" * 129}, "password"),
        ("a bad email", {"email": "nope", "password": PASSWORD}, "email"),
        ("a missing email", {"password": PASSWORD}, "email"),
        ("a very long email", {"email": "a" * 250 + "@example.com", "password": PASSWORD}, "email"),
        (
            "an unknown field",
            {"email": "a@example.com", "password": PASSWORD, "isAdmin": True},
            "isAdmin",
        ),
        ("a wrong type", {"email": 5, "password": PASSWORD}, "email"),
    ],
)
async def test_registration_rejects_invalid_input(
    database: Database, label: str, body: dict[str, object], field: str
) -> None:
    async with api(database) as client:
        response = await client.http.post("/v1/users", json=body)
    assert_problem(response, 400, "validation-failed")
    assert_field_error(response, field)


async def test_registration_lists_every_invalid_field_at_once(database: Database) -> None:
    async with api(database) as client:
        response = await client.http.post(
            "/v1/users", json={"email": "nope", "password": "short", "isAdmin": True}
        )
    for field in ("email", "password", "isAdmin"):
        assert_field_error(response, field)


async def test_login_returns_a_token_that_is_not_stored_in_plain_text(
    database: Database, owner: psycopg.AsyncConnection
) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        response = await client.http.post(
            "/v1/sessions", json={"email": user.email, "password": PASSWORD}
        )
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    assert datetime.fromisoformat(response.json()["expiresAt"]) > datetime.now(UTC)
    stored = await (
        await owner.execute(
            "select count(*) from sessions where token_hash = %s", [response.json()["token"]]
        )
    ).fetchone()
    assert stored == (0,)


@pytest.mark.parametrize("delivery", [None, "body"])
async def test_body_login_returns_the_token_and_sets_no_cookie(
    database: Database, delivery: str | None
) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        body = {"email": user.email, "password": PASSWORD}
        response = await client.http.post(
            "/v1/sessions", json=body | ({"delivery": delivery} if delivery else {})
        )
    assert response.status_code == 201
    assert set(response.json()) == {"token", "expiresAt"}
    assert "set-cookie" not in response.headers


async def test_cookie_login_sets_an_httponly_host_cookie_instead_of_returning_the_token(
    database: Database,
) -> None:
    async with api(database, SESSION_TTL_HOURS="2") as client:
        user = await client.sign_up()
        response = await cookie_login(client, user.email)
        again = await cookie_login(client, user.email)
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    assert set(response.json()) == {"expiresAt"}
    assert datetime.fromisoformat(response.json()["expiresAt"]) > datetime.now(UTC)
    attributes = [part.strip() for part in response.headers["set-cookie"].split(";")]
    assert attributes[0].startswith("__Host-session=")
    assert len(attributes[0]) > len("__Host-session=") + 40
    assert {attribute.lower() for attribute in attributes[1:]} == {
        "path=/",
        "max-age=7200",
        "httponly",
        "secure",
        "samesite=strict",
    }
    assert session_cookie(response) != session_cookie(again)


async def test_login_rejects_an_unknown_delivery(database: Database) -> None:
    async with api(database) as client:
        response = await client.http.post(
            "/v1/sessions", json={"email": email(), "password": PASSWORD, "delivery": "header"}
        )
    assert_problem(response, 400, "validation-failed")
    assert_field_error(response, "delivery")


async def test_registration_rejects_a_delivery(database: Database) -> None:
    async with api(database) as client:
        response = await client.http.post(
            "/v1/users", json={"email": email(), "password": PASSWORD, "delivery": "cookie"}
        )
    assert_problem(response, 400, "validation-failed")
    assert_field_error(response, "delivery")


async def test_login_gives_a_wrong_password_and_an_unknown_email_the_same_answer(
    database: Database,
) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        for credentials in (
            {"email": user.email, "password": "wrong-horse-battery"},
            {"email": email(), "password": PASSWORD},
        ):
            response = await client.http.post("/v1/sessions", json=credentials)
            body = assert_problem(response, 401, "invalid-credentials")
            assert body["detail"] == "The email or password is wrong."


async def test_returns_the_current_user(database: Database) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        response = await user.request("GET", "/v1/users/me")
    assert response.json()["id"] == user.id


@pytest.mark.parametrize(
    "header", [None, "Bearer not-a-real-token-at-all", "Basic dXNlcjpwYXNz", "Bearer"]
)
async def test_rejects_a_missing_or_bad_token(database: Database, header: str | None) -> None:
    async with api(database) as client:
        headers = {"Authorization": header} if header else {}
        response = await client.http.get("/v1/users/me", headers=headers)
    assert_problem(response, 401, "unauthorized")
    assert response.headers["www-authenticate"] == "Bearer"
    assert "set-cookie" not in response.headers


async def test_authenticates_with_only_the_session_cookie(database: Database) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        cookie = session_cookie(await cookie_login(client, user.email))
        response = await client.http.get("/v1/users/me", headers=cookie)
    assert response.status_code == 200
    assert response.json()["id"] == user.id


async def test_prefers_the_authorization_header_over_the_cookie(database: Database) -> None:
    async with api(database) as client:
        first = await client.sign_up()
        second = await client.sign_up()
        cookie = session_cookie(await cookie_login(client, second.email))
        response = await first.request("GET", "/v1/users/me", headers=cookie)
    assert response.json()["id"] == first.id


@pytest.mark.parametrize("header", ["Bearer not-a-real-token-at-all", "Basic dXNlcjpwYXNz", ""])
async def test_rejects_a_bad_header_even_with_a_valid_cookie(
    database: Database, header: str
) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        cookie = session_cookie(await cookie_login(client, user.email))
        response = await client.http.get("/v1/users/me", headers={"Authorization": header} | cookie)
    assert_problem(response, 401, "unauthorized")
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize(
    "statement",
    [
        "update sessions set expires_at = now() - interval '1 second' "
        "where user_id = (select id from users where email = %s)",
        "delete from sessions where user_id = (select id from users where email = %s)",
    ],
)
async def test_rejects_an_expired_or_revoked_cookie_and_clears_it(
    database: Database, owner: psycopg.AsyncConnection, statement: str
) -> None:
    async with api(database) as client:
        address = email()
        await client.http.post("/v1/users", json={"email": address, "password": PASSWORD})
        cookie = session_cookie(await cookie_login(client, address))
        await owner.execute(statement, [address])
        response = await client.http.get("/v1/users/me", headers=cookie)
        unknown = await client.http.get(
            "/v1/users/me", headers={"Cookie": "__Host-session=not-a-real-token"}
        )
    body = assert_problem(response, 401, "unauthorized")
    assert "Bearer <token>" in body["detail"]
    assert 'delivery: "cookie"' in body["detail"]
    assert response.headers["www-authenticate"] == "Bearer"
    assert_clears_the_cookie(response)
    assert_clears_the_cookie(unknown)


async def test_logout_with_the_cookie_revokes_and_clears_it(database: Database) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        cookie = session_cookie(await cookie_login(client, user.email))
        logout = await client.http.delete("/v1/sessions/current", headers=cookie)
        after = await client.http.get("/v1/users/me", headers=cookie)
    assert logout.status_code == 204
    assert_clears_the_cookie(logout)
    assert_problem(after, 401, "unauthorized")


async def test_logout_with_a_bearer_token_also_clears_the_cookie(database: Database) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        response = await user.request("DELETE", "/v1/sessions/current")
    assert response.status_code == 204
    assert_clears_the_cookie(response)


async def test_rejects_an_expired_session(
    database: Database, owner: psycopg.AsyncConnection
) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        await owner.execute(
            "update sessions set expires_at = now() - interval '1 second' "
            "where user_id = (select id from users where email = %s)",
            [user.email],
        )
        response = await user.request("GET", "/v1/users/me")
    assert_problem(response, 401, "unauthorized")


async def test_logout_revokes_only_the_current_session(database: Database) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        second = await client.http.post(
            "/v1/sessions", json={"email": user.email, "password": PASSWORD}
        )
        other = {"Authorization": f"Bearer {second.json()['token']}"}
        assert (await user.request("DELETE", "/v1/sessions/current")).status_code == 204
        assert_problem(await user.request("GET", "/v1/users/me"), 401, "unauthorized")
        assert (await client.http.get("/v1/users/me", headers=other)).status_code == 200


async def test_hashing_and_verifying_passwords_run_off_the_event_loop(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    threads: list[int] = []

    def hash_password(password: str) -> str:
        threads.append(threading.get_ident())
        return security.hash_password(password)

    def verify_password(password: str, stored: str) -> bool:
        threads.append(threading.get_ident())
        return security.verify_password(password, stored)

    monkeypatch.setattr(routes, "hash_password", hash_password)
    monkeypatch.setattr(routes, "verify_password", verify_password)
    async with api(database) as client:
        await client.sign_up()
    assert len(threads) == 2
    assert threading.get_ident() not in threads


async def login(client: Api, address: str, password: str) -> httpx2.Response:
    return await client.http.post("/v1/sessions", json={"email": address, "password": password})


async def test_login_locks_an_account_after_too_many_failures_even_for_the_right_password(
    database: Database,
) -> None:
    async with api(database, LOGIN_FAILURE_LIMIT="2") as client:
        user = await client.sign_up()
        failures = [await login(client, user.email, "wrong-horse-battery") for _ in range(2)]
        blocked = await login(client, f"  {user.email.upper()} ", PASSWORD)
    assert [response.status_code for response in failures] == [401, 401]
    assert all('"login"' not in response.headers["ratelimit-policy"] for response in failures)
    body = assert_problem(blocked, 429, "rate-limited")
    assert body["detail"].startswith("Too many failed logins for this account. Retry in ")
    assert blocked.headers["ratelimit-policy"].endswith(', "login";q=2;w=900')
    remaining, _, reset = blocked.headers["ratelimit"].removeprefix('"login";r=').partition(";t=")
    assert remaining == "0"
    assert 1 <= int(reset) <= 900
    assert blocked.headers["retry-after"] == reset


async def test_login_limits_an_unknown_email_the_same_way(database: Database) -> None:
    address = email()
    async with api(database, LOGIN_FAILURE_LIMIT="1") as client:
        first = await login(client, address, PASSWORD)
        second = await login(client, address, PASSWORD)
        other = await login(client, email(), PASSWORD)
    assert_problem(first, 401, "invalid-credentials")
    assert_problem(second, 429, "rate-limited")
    assert_problem(other, 401, "invalid-credentials")


async def test_login_counts_only_failures_and_successes_never_reset_them(
    database: Database,
) -> None:
    async with api(database, LOGIN_FAILURE_LIMIT="2") as client:
        user = await client.sign_up()
        statuses = [
            (await login(client, user.email, password)).status_code
            for password in (
                PASSWORD,
                PASSWORD,
                PASSWORD,
                "wrong-horse-battery",
                PASSWORD,
                "wrong-horse-battery",
                PASSWORD,
            )
        ]
    assert statuses == [201, 201, 201, 401, 201, 401, 429]


async def test_login_checks_the_failure_limit_atomically(database: Database) -> None:
    async with api(database, LOGIN_FAILURE_LIMIT="3") as client:
        user = await client.sign_up()
        responses = await asyncio.gather(
            *(login(client, user.email, "wrong-horse-battery") for _ in range(8))
        )
    statuses = sorted(response.status_code for response in responses)
    assert statuses == [401, 401, 401, 429, 429, 429, 429, 429]


async def test_login_accepts_a_password_shorter_than_the_registration_minimum(
    database: Database, owner: psycopg.AsyncConnection
) -> None:
    address = email()
    await owner.execute(
        "insert into users (email, password_hash) values (%s, %s)",
        [address, security.hash_password("old-short")],
    )
    async with api(database) as client:
        response = await login(client, address, "old-short")
        empty = await login(client, address, "")
    assert response.status_code == 201, response.text
    assert_problem(empty, 400, "validation-failed")


async def test_accepts_the_bearer_scheme_in_any_case(database: Database) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        responses = [
            await client.http.get(
                "/v1/users/me", headers={"Authorization": f"{scheme} {user.token}"}
            )
            for scheme in ("bearer", "BEARER", "Bearer")
        ]
    assert [response.status_code for response in responses] == [200, 200, 200]
