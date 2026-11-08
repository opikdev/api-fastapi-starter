# Agent guide

A production-ready Python API: FastAPI, SQLAlchemy, Alembic, and Postgres, with procrastinate background jobs, auth, rate limits, and Problem Details errors. `notes` is the sample feature to copy or replace.

| Path | Purpose |
|---|---|
| [docs/architecture.md](docs/architecture.md) | How requests flow and which module does what |
| [docs/customize.md](docs/customize.md) | How to add a feature, rename the project, or remove a module |
| [docs/jobs.md](docs/jobs.md) | How to add and run background jobs |
| [docs/client.md](docs/client.md) | How to call the API with the generated client |
| [docs/errors.md](docs/errors.md) | Every problem type the API can return |
| [docs/operations.md](docs/operations.md) | Configuration, deploys, migrations, backups, and tracing |
| [docs/decisions/](docs/decisions/) | Why it's built this way |
| `.agents/skills/` | Step-by-step guides for recurring tasks |
| `.mcp.json` | MCP servers for this project |

## Commands

| Task | Command |
|---|---|
| Run everything | `docker compose up --build --wait api worker` |
| Run the API on your machine | `docker compose up --wait db`, then `make migrate seed dev` |
| Run all gates | `make verify` |
| Test against the real Docker images | `make e2e` |
| Regenerate `openapi.json` and the client | `make client` |
| Create a migration | `uv run --env-file .env alembic revision --autogenerate -m "<what changed>"` |

## Rules

- Don't commit until `make verify` passes. Tests need Docker, or `TEST_DATABASE_URL` set to a Postgres 18 server. If neither is available, stop and report that instead of committing.
- Run `make verify` before calling work done. For changes to Docker, Compose, startup, or jobs, run `make e2e` too.
- If the check blocks you, fix the cause. Never edit `.agents/check.sh`, `.githooks/`, or the harness workflow to get past it, and never use `--no-verify`. If the request can't be done without that, stop and ask.
- After cloning, run `git config core.hooksPath .githooks` once to turn on the hook.
- When a route changes, run `make client`, and commit `openapi.json` and `clients/python` in the same change. CI fails otherwise.
- Change tables in `src/app/db.py`, then autogenerate a migration and read it. Migrations are append-only, so never edit one that's committed. A test fails if the models and migrations disagree.
- Raise `ProblemError` for every failure, and add new types to `src/app/problems.py` and `docs/errors.md`.
- Scope every query on a resource to the caller's user ID. Return 404, not 403, for someone else's resource.
- Features don't import each other, except for `features/auth/dependencies.py`. `tests/unit/test_architecture.py` enforces this.
- Put work that can wait, or that calls slow outside systems, in a job in `src/app/jobs.py`. Jobs may run more than once, so make them safe to retry.
- Add dependencies with `uv add`, and commit `uv.lock` in the same change.
- Don't edit files listed in `.baseline.sha256`. They come from [opikdev/starters](https://github.com/opikdev/starters).
- Keep this file a short map, and put detail in `docs/`.
- Fix any doc your change makes wrong, in the same change.
- Record significant decisions with the `record-decision` skill.
- Back important rules with a lint rule, hook, or CI check.
