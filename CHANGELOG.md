# Changelog

All notable changes to this repo are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed

- `DbSession` and `get_session` moved from `app.db` to `app.dependencies`, so jobs no longer load FastAPI through `app.db`. Update imports in your features.
- `tests/unit/test_architecture.py` finds every feature on its own and checks that jobs never load FastAPI, even indirectly. Ruff now bans relative imports.

### Fixed

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
