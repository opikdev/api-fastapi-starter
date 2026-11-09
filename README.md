# API FastAPI starter

A production-ready Python API you can run with one command and customize with coding agents. It uses FastAPI, SQLAlchemy, Alembic, and Postgres, with background jobs, auth, rate limits, a generated client, tests, and tracing already wired in.

[![CI](https://github.com/opikdev/api-fastapi-starter/actions/workflows/ci.yml/badge.svg)](https://github.com/opikdev/api-fastapi-starter/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## Features

- **Typed end to end:** Pydantic models define every request and response, and `openapi.json` is committed and checked. Docs are at `/docs`.
- **Generated client:** a typed Python client in `clients/python`, generated from the spec and used by the end-to-end tests. See [Call the API](docs/client.md).
- **Background jobs:** procrastinate runs jobs from Postgres, with retries and an hourly cleanup, so there's no Redis to run. See [Run background jobs](docs/jobs.md).
- **Auth:** registration, login, and revocable session tokens, with argon2id password hashes and per-user data access.
- **Reliable by default:** rate limits, idempotency keys, optimistic concurrency, and cursor pagination.
- **Consistent errors:** RFC 9457 Problem Details everywhere. See the [error reference](docs/errors.md).
- **Safe data layer:** Alembic migrations checked against the models, constraints in the database, and an app role that can't change the schema.
- **Ready to operate:** a non-root Docker image, health checks, JSON logs, and OpenTelemetry traces.
- **Agent-ready:** `AGENTS.md`, skills, and checks that run on every commit.
- **Strict gates:** Ruff, mypy in strict mode, 90% coverage, architecture tests, and real end-to-end tests.

It has the same API and behavior as [api-hono-starter](https://github.com/opikdev/api-hono-starter) and [api-go-starter](https://github.com/opikdev/api-go-starter), so a client works with any of them.

## Quick start

You only need Docker:

```sh
git clone https://github.com/opikdev/api-fastapi-starter
cd api-fastapi-starter
docker compose up --build --wait api worker
```

The API is now at <http://localhost:3000>, with interactive docs at <http://localhost:3000/docs>. Log in with the fake seed user:

```sh
curl -X POST localhost:3000/v1/sessions \
  -H 'Content-Type: application/json' \
  -d '{"email":"demo@example.com","password":"demo-password-123"}'
```

Send the returned token to list the seeded notes:

```sh
curl localhost:3000/v1/notes -H 'Authorization: Bearer <YOUR_TOKEN>'
```

If port 3000 or 5432 is taken, set `PORT` or `POSTGRES_PORT` before running Compose.

## Usage

To work on the code, you need [uv](https://docs.astral.sh/uv/), which installs Python 3.15 for you:

```sh
make sync
cp .env.example .env
docker compose up --wait db
make migrate seed dev
```

`make dev` serves with auto-reload. Run `make worker` in another terminal to process jobs. The `make` targets load `.env` with `uv run --env-file`.

| Task | Command |
|---|---|
| Run lint, types, generated-code checks, tests with coverage, and repo checks | `make verify` |
| Test the real images end to end | `make e2e` |
| Regenerate `openapi.json` and the client after changing a route | `make client` |
| Create a migration after changing `src/app/db.py` | `uv run --env-file .env alembic revision --autogenerate -m "<what changed>"` |
| Apply migrations, then add demo data | `make migrate seed` |

Tests start their own Postgres, so Docker must be running. Without Docker, point them at a Postgres 18 server instead:

```sh
TEST_DATABASE_URL=postgresql://<SUPERUSER>@localhost:5432/postgres make verify
```

The dev container in `.devcontainer/` runs Postgres next to the code and sets `TEST_DATABASE_URL`, so `make verify` works inside it. `make e2e` needs Docker, so run it on the host.

Each run creates a temporary database and drops it afterward, so existing data is never touched. To add a feature, rename the project, or remove a module, see [Customize the starter](docs/customize.md). Before you deploy, read [Operate the API](docs/operations.md).

## Project structure

| Path | Purpose |
|---|---|
| `src/app/features/` | Routes and models for each feature. `notes` is the sample to copy |
| `src/app/` | The app factory, middleware, errors, rate limits, jobs, and settings |
| `src/app/db.py`, `src/app/migrations/` | Tables, the engine, and Alembic migrations |
| `clients/python/` | The client generated from `openapi.json` |
| `tests/` | Unit, integration, and end-to-end tests |
| `docs/` | [Architecture](docs/architecture.md), guides, and [decisions](docs/decisions/) |

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request, and follow the [code of conduct](CODE_OF_CONDUCT.md).

## Security

Report vulnerabilities privately, as described in [SECURITY.md](SECURITY.md).

## License

Released under the [MIT License](LICENSE).
