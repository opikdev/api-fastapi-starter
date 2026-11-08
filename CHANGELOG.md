# Changelog

All notable changes to this repo are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
