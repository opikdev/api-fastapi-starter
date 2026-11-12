import json
import logging
from uuid import UUID

import pytest
from opentelemetry.sdk.trace import TracerProvider
from starlette.requests import HTTPConnection

from app.config import ConfigError, database_url, load_settings
from app.ids import Prefix, format_id, parse_id
from app.log import JsonFormatter, configure_logging
from app.main import create_app
from app.ratelimit import Policy, Usage, client_ip, client_key, response_headers
from app.security import DUMMY_HASH, hash_password, hash_token, new_token, verify_password

URL = "postgresql://api_app:pw@localhost:5432/api"


def test_settings_have_safe_defaults() -> None:
    settings = load_settings({"DATABASE_URL": URL})
    assert (settings.port, settings.session_ttl_hours, settings.origins) == (3000, 168, [])
    assert (settings.rate_limit_per_minute, settings.auth_rate_limit_per_minute) == (300, 10)
    assert settings.trust_proxy_hops == 0
    assert settings.database_pool_max == 10
    assert (settings.login_failure_limit, settings.login_failure_window_seconds) == (5, 900)
    assert (settings.shutdown_drain_seconds, settings.shutdown_timeout_seconds) == (5, 30)
    assert settings.keep_alive_timeout_seconds == 75
    assert settings.docs_enabled is False


def test_settings_refuse_a_shutdown_timeout_shorter_than_the_slowest_query() -> None:
    with pytest.raises(ConfigError) as error:
        load_settings(
            {
                "DATABASE_URL": URL,
                "SHUTDOWN_TIMEOUT_SECONDS": "4",
                "DATABASE_STATEMENT_TIMEOUT_MS": "5000",
            }
        )
    assert "SHUTDOWN_TIMEOUT_SECONDS must be at least DATABASE_STATEMENT_TIMEOUT_MS" in str(
        error.value
    )


def test_settings_allow_a_session_ttl_up_to_the_browser_cookie_limit() -> None:
    settings = load_settings({"DATABASE_URL": URL, "SESSION_TTL_HOURS": "9600"})
    assert settings.session_ttl_hours == 9600


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
        ({"DATABASE_URL": URL, "TRUST_PROXY_HOPS": "-1"}, "TRUST_PROXY_HOPS"),
        ({"DATABASE_URL": URL, "SESSION_TTL_HOURS": "9601"}, "SESSION_TTL_HOURS"),
    ],
)
def test_settings_name_each_bad_variable_without_its_value(
    env: dict[str, str], name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Settings also read the process environment, which a dev container fills in.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ConfigError, match=name) as error:
        load_settings(env)
    assert "pw@" not in str(error.value)


@pytest.mark.parametrize(
    ("value", "level"),
    [
        ("debug", "DEBUG"),
        ("info", "INFO"),
        ("warn", "WARNING"),
        ("warning", "WARNING"),
        ("error", "ERROR"),
    ],
)
def test_log_level_accepts_each_documented_value(value: str, level: str) -> None:
    root = logging.getLogger()
    handlers, previous = root.handlers[:], root.level
    try:
        configure_logging(load_settings({"DATABASE_URL": URL, "LOG_LEVEL": value}).log_level)
        assert logging.getLevelName(root.level) == level
    finally:
        root.handlers[:] = handlers
        root.setLevel(previous)


def test_settings_refuse_the_replaced_trust_proxy() -> None:
    with pytest.raises(ConfigError) as error:
        load_settings({"DATABASE_URL": URL, "TRUST_PROXY": "true"})
    assert str(error.value) == (
        "TRUST_PROXY was replaced by TRUST_PROXY_HOPS. Set TRUST_PROXY_HOPS=1 for the old behavior."
    )


def connection(*forwarded: str) -> HTTPConnection:
    headers = [(b"x-forwarded-for", value.encode()) for value in forwarded]
    return HTTPConnection({"type": "http", "headers": headers, "client": ("10.0.0.9", 5000)})


@pytest.mark.parametrize(
    ("hops", "forwarded", "expected"),
    [
        (0, ["198.51.100.7"], "10.0.0.9"),
        (0, [], "10.0.0.9"),
        (1, ["1.1.1.1, 198.51.100.7"], "198.51.100.7"),
        (1, [" 198.51.100.7 "], "198.51.100.7"),
        (2, ["1.1.1.1, 198.51.100.7, 10.0.0.2"], "198.51.100.7"),
        (2, ["1.1.1.1, 198.51.100.7", "10.0.0.2"], "198.51.100.7"),
        (3, ["198.51.100.7, 10.0.0.2"], "198.51.100.7"),
        (1, [], "10.0.0.9"),
        (1, ["1.1.1.1, "], "10.0.0.9"),
        (1, ["not-an-ip"], "10.0.0.9"),
        (1, ["2001:db8::1"], "2001:db8::1"),
    ],
)
def test_client_ip_trusts_only_the_configured_proxy_hops(
    hops: int, forwarded: list[str], expected: str
) -> None:
    assert client_ip(connection(*forwarded), hops) == expected


@pytest.mark.parametrize(
    ("forwarded", "expected"),
    [
        ("198.51.100.7", "198.51.100.7"),
        ("::ffff:198.51.100.7", "198.51.100.7"),
        ("2001:db8:1:2:3:4:5:6", "2001:db8:1:2::/64"),
        ("2001:db8:1:2::", "2001:db8:1:2::/64"),
        ("2001:db8:1:3::1", "2001:db8:1:3::/64"),
        ("::1", "::/64"),
    ],
)
def test_client_key_keeps_ipv4_whole_and_groups_ipv6_by_its_64_prefix(
    forwarded: str, expected: str
) -> None:
    assert client_key(connection(forwarded), 1) == expected


def test_client_key_keeps_a_socket_name_that_is_not_an_ip() -> None:
    socket = HTTPConnection({"type": "http", "headers": [], "client": ("testclient", 5000)})
    assert client_key(socket, 0) == "testclient"


GLOBAL = Policy("global", 300, 60)
AUTH = Policy("auth", 10, 60)


def test_ratelimit_headers_list_every_counted_policy_and_its_state() -> None:
    headers = response_headers([Usage(GLOBAL, 62, 25), Usage(AUTH, 1, 55)])
    assert headers == {
        "RateLimit-Policy": '"global";q=300;w=60, "auth";q=10;w=60',
        "RateLimit": '"global";r=238;t=25, "auth";r=9;t=55',
    }


def test_ratelimit_headers_describe_only_the_exceeded_policy_on_a_429() -> None:
    headers = response_headers([Usage(GLOBAL, 62, 25), Usage(AUTH, 11, 55)])
    assert headers["RateLimit"] == '"auth";r=0;t=55'
    assert headers["RateLimit-Policy"] == '"global";q=300;w=60, "auth";q=10;w=60'


def test_ratelimit_headers_are_absent_when_nothing_was_counted() -> None:
    assert response_headers([]) == {}


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


def log_line(record: logging.LogRecord) -> dict[str, object]:
    entry: dict[str, object] = json.loads(JsonFormatter().format(record))
    return entry


def test_json_logs_drop_uvicorns_color_copy_of_the_message() -> None:
    record = logging.makeLogRecord(
        {"msg": "Started", "levelname": "INFO", "color_message": "\x1b[36mStarted\x1b[0m"}
    )
    entry = log_line(record)
    assert entry["msg"] == "Started"
    assert "color_message" not in entry


def test_json_logs_carry_the_active_trace_and_span_ids() -> None:
    record = logging.makeLogRecord({"msg": "Inside", "levelname": "INFO"})
    assert "trace_id" not in log_line(record)
    with TracerProvider().get_tracer("test").start_as_current_span("work") as span:
        entry = log_line(record)
    context = span.get_span_context()
    assert entry["trace_id"] == format(context.trace_id, "032x")
    assert entry["span_id"] == format(context.span_id, "016x")
    assert len(str(entry["trace_id"])) == 32
    assert len(str(entry["span_id"])) == 16
