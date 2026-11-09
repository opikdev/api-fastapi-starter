from uuid import UUID

import pytest

from app.config import ConfigError, database_url, load_settings
from app.ids import Prefix, format_id, parse_id
from app.main import create_app
from app.security import DUMMY_HASH, hash_password, hash_token, new_token, verify_password

URL = "postgresql://api_app:pw@localhost:5432/api"


def test_settings_have_safe_defaults() -> None:
    settings = load_settings({"DATABASE_URL": URL})
    assert (settings.port, settings.session_ttl_hours, settings.origins) == (3000, 168, [])
    assert (settings.rate_limit_per_minute, settings.auth_rate_limit_per_minute) == (300, 10)
    assert settings.trust_proxy is False
    assert settings.database_pool_max == 10


def test_the_app_engine_uses_database_pool_max() -> None:
    app = create_app(load_settings({"DATABASE_URL": URL, "DATABASE_POOL_MAX": "3"}))
    assert app.state.sessions.kw["bind"].pool.size() == 3


def test_settings_split_cors_origins_and_ignore_empty_values() -> None:
    settings = load_settings(
        {"DATABASE_URL": URL, "CORS_ORIGINS": "https://a.test, https://b.test", "PORT": ""}
    )
    assert settings.origins == ["https://a.test", "https://b.test"]
    assert settings.port == 3000


@pytest.mark.parametrize(
    ("env", "name"),
    [
        ({}, "DATABASE_URL"),
        ({"DATABASE_URL": URL, "PORT": "0"}, "PORT"),
        ({"DATABASE_URL": URL, "LOG_LEVEL": "loud"}, "LOG_LEVEL"),
        ({"DATABASE_URL": URL, "DATABASE_POOL_MAX": "0"}, "DATABASE_POOL_MAX"),
    ],
)
def test_settings_name_each_bad_variable_without_its_value(env: dict[str, str], name: str) -> None:
    with pytest.raises(ConfigError, match=name) as error:
        load_settings(env)
    assert "pw@" not in str(error.value)


@pytest.mark.parametrize("prefix", ["postgres://", "postgresql://", "postgresql+psycopg://"])
def test_database_urls_use_the_psycopg_driver(prefix: str) -> None:
    assert database_url(f"{prefix}u@h/db") == "postgresql+psycopg://u@h/db"


def test_passwords_hash_with_argon2id_and_verify() -> None:
    stored = hash_password("correct-horse-battery")
    assert stored.startswith("$argon2id$v=19$m=19456,t=2,p=1$")
    assert verify_password("correct-horse-battery", stored)
    assert not verify_password("wrong-horse-battery", stored)
    assert not verify_password("anything", "not-a-hash")
    assert not verify_password("anything", DUMMY_HASH)


def test_tokens_are_random_and_only_their_hash_is_stored() -> None:
    first, first_hash = new_token()
    second, _ = new_token()
    assert first != second
    assert len(first) >= 43
    assert first_hash == hash_token(first) != first
    assert len(first_hash) == 64


def test_public_ids_round_trip_and_reject_other_kinds() -> None:
    value = UUID("0190a7e4-c1d2-7c3e-9b8f-6a5d4c3b2a10")
    note = format_id(Prefix.NOTE, value)
    assert note == "note_0190a7e4c1d27c3e9b8f6a5d4c3b2a10"
    assert parse_id(Prefix.NOTE, note) == value
    for bad in (
        "usr_0190a7e4c1d27c3e9b8f6a5d4c3b2a10",
        "note_xyz",
        "note",
        "",
        "note_0190A7E4C1D27C3E9B8F6A5D4C3B2A10",
    ):
        assert parse_id(Prefix.NOTE, bad) is None
