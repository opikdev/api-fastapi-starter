# Changelog

All notable changes to this repo are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- A test that fails when `docs/errors.md` and the problem catalog list different types.
- Migration `0002`, which indexes `sessions.user_id`, so deleting a user doesn't scan every session. On a large `sessions` table, build it concurrently first, as `docs/operations.md` explains.
- `DATABASE_POOL_MAX`, the API's database pool size. It defaults to 10, as before.

### Changed

- **Breaking:** `TRUST_PROXY` is replaced by `TRUST_PROXY_HOPS`, the number of proxies that append to `X-Forwarded-For`. `0`, the default, ignores the header. Set `TRUST_PROXY_HOPS=1` for the old `TRUST_PROXY=true`. The API refuses to start while `TRUST_PROXY` is set, and it falls back to the socket address when the chosen entry isn't an IP address.
- `DbSession` and `get_session` moved from `app.db` to `app.dependencies`, so jobs no longer load FastAPI through `app.db`. Update imports in your features.
- `tests/unit/test_architecture.py` finds every feature on its own and checks that jobs never load FastAPI, even indirectly. Ruff now bans relative imports.

### Fixed

- CORS responses expose `ETag`, `Location`, `X-Request-Id`, `Retry-After`, the `RateLimit-*` headers, and `Idempotency-Replayed` to browser scripts. Only the preflight listed some of them before, where browsers ignore it.
- An expired `Idempotency-Key` creates a new note instead of replaying the old one, as it did until the hourly cleanup removed it.
- Idempotency keys are scoped to the endpoint as well as the user, so an endpoint that adds idempotency can't replay another's response. Migration `0003` changes the key's unique constraint. Idempotent `POST /v1/notes` requests on the old version fail until the new version is rolled out, so deploy both together.
- `LOG_LEVEL=warn`, as documented, no longer stops the API from starting. `warning` still works.
- Registration queues the welcome email in the same transaction as the user. A queueing failure used to return 500 but keep the user, so a retry got 409 and no email ever went out.
- Jobs and `seed` read their settings through `Settings` when they start, not from `os.environ` when `app.jobs` is imported. Jobs get the database from `context.additional_context`, and the API no longer opens a queue pool.
- Password hashing and checks run in a thread, so registration and login no longer block other requests.
- Migration `0001` creates procrastinate's tables from a frozen copy of its 3.10.0 schema instead of the installed package, so upgrading procrastinate no longer changes what `0001` does. The SQL is identical, and a test fails when the installed procrastinate is ahead of the migrations.

## [0.1.0] - 2026-11-08

### Added

- FastAPI app with a committed OpenAPI 3.1 document, Problem Details errors, and a sample notes feature.
- A typed Python client generated from the document, used by the end-to-end tests.
- Session auth with argon2id, rate limits, idempotency keys, and optimistic concurrency.
- Postgres with SQLAlchemy, Alembic migrations checked against the models, seed data, and separate app and owner roles.
- Background jobs on Postgres with procrastinate: a welcome email after registration, and an hourly cleanup.
- `TEST_DATABASE_URL`, which runs tests against an existing Postgres 18 server instead of Docker.
- Docker image, and a Compose stack with the API and a worker.
- Structured logs, OpenTelemetry tracing, and error recording.
- `pik.yaml`, so `pik new api-fastapi-starter` can create projects from this starter.
