import secrets
import threading
from datetime import UTC, datetime

import psycopg
import pytest

from app import security
from app.features.auth import routes
from tests.conftest import Database
from tests.helpers import PASSWORD, api, assert_field_error, assert_problem

pytestmark = pytest.mark.anyio


def email() -> str:
    return f"user-{secrets.token_hex(6)}@example.com"


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
