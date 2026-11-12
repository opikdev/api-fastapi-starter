# Changelog

All notable changes to this repo are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.4.0] - 2026-11-12

### Security

- Rate limits key IPv6 clients by their /64, and IPv4-mapped IPv6 addresses as IPv4, so one host can't rotate addresses for a fresh budget.
- `POST /v1/sessions` locks an email after `LOGIN_FAILURE_LIMIT` failed logins (default 5) for `LOGIN_FAILURE_WINDOW_SECONDS` (default 900), keyed by a hash of the email whether or not the account exists. Its 429 still costs a password hash, so it reveals nothing.
- Every response sends `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`, and `/docs` gets a CSP that allows only its own scripts and styles.
- Every `/v1` response sends `Cache-Control: no-store`, not just login.
- `/docs` serves Swagger UI from the pinned `fastapi-swagger` package instead of jsDelivr, with no inline script and no third-party favicon.
- The image drops pip, pins its base images by digest, and the release scans it with Trivy before pushing, then publishes an SBOM and a build provenance attestation. CI scans it too.
- `docker/postgres/init.sql` no longer holds a password. Compose sets the `api_app` password from `APP_DB_PASSWORD`, and `docs/deploy.md` shows how to set it from a secret store.

### Changed

- **Breaking:** rate-limit headers follow draft-ietf-httpapi-ratelimit-headers: `RateLimit-Policy` and `RateLimit` replace `RateLimit-Limit`, `RateLimit-Remaining`, and `RateLimit-Reset`. On a 429, `RateLimit` and `Retry-After` describe only the limit that was exceeded. CORS exposes the new headers.
- **Breaking:** `/docs` and `/openapi.json` return 404 unless `DOCS_ENABLED` is `true`. `.env.example`, Compose, and the tests turn it on.
- The OpenAPI title is the project name, `api-fastapi-starter`, and the version comes from `pyproject.toml`. Problem responses and headers are shared components, and every operation documents the problems middleware can return, such as 403, 413, 415, 429, and 500.
- **Breaking:** `validation-failed` entries about the whole body, such as malformed JSON or `PATCH {}`, have `field: ""` instead of `"body"`.
- Login accepts any non-empty password, so a stricter registration policy can't lock out existing users. Registration still needs 12 to 128 characters.
- `If-Match: *` updates a note at any version, a list of ETags matches if any one does, and weak ETags get 412 with a detail that says they never match.
- The idempotency fingerprint hashes the method, path, and canonical JSON of the whole validated body, so new fields are covered.
- Uvicorn runs with its `standard` extras, uvloop and httptools, and keeps idle connections for `KEEP_ALIVE_TIMEOUT_SECONDS` (default 75), above common load balancer idle timeouts.
- `/healthz` and `/readyz` log at `debug` and aren't traced.
- Compose builds the image once and runs it read-only for migrate, seed, api, and worker.
- `pik new` renames the README title and the OpenAPI title, resets the version to 0.1.0, and starts a fresh `CHANGELOG.md`.
- FastAPI is 0.162.5 and procrastinate is 3.11.0. Migration `0004` applies procrastinate's 3.11.0 schema change.
- `renovate.json` waits 3 days before proposing a release and pins Docker digests.

### Added

- Graceful drain: on `SIGTERM`, `/readyz` returns 503 while the API keeps serving for `SHUTDOWN_DRAIN_SECONDS` (default 5), then in-flight requests get `SHUTDOWN_TIMEOUT_SECONDS` (default 30). The worker waits the same timeout for running jobs. Compose sets `stop_grace_period: 40s`.
- `migrate` holds a Postgres advisory lock and sets `lock_timeout` to 5 seconds, so concurrent runs both succeed and DDL never stalls traffic for long.
- A `retry_stalled_jobs` job every 5 minutes, which retries jobs left `doing` by a worker that died.
- OpenTelemetry metrics over OTLP whenever traces are exported, with HTTP server and database pool metrics. Worker jobs are traced, and JSON log lines carry `trace_id` and `span_id`.
- Constraint violations that reach the error handler become problems without internals: unique and foreign key violations are 409 `conflict`, and check violations are 400 `validation-failed`.
- `make migration name="..."` numbers revisions in order, and Alembic runs Ruff on each new revision. A test enforces the numbering.
- `docs/deploy.md`, a go-live guide, and ADRs 008 and 009.

### Fixed

- The image health check imports only the standard library. It took over a second, and over 8 seconds on a quarter CPU, past its 3-second timeout.
- The OpenAPI document keeps the real 422 `idempotency-key-reused` on `POST /v1/notes`, and drops only FastAPI's default validation 422.
- The release workflow runs the end-to-end tests and the migration check before it publishes.
- `make check-generated` explains what to stage instead of printing a raw diff, and catches new untracked client files.
- `POSTGRES_PORT` reaches the `make` targets through `.env.example`.
- Uvicorn's `color_message` field, with terminal color codes, no longer appears in JSON logs.
- The security workflow's SBOM job has read-only permissions.

## [0.3.0] - 2026-11-11

### Added

- The README explains how to start a project with `pik new` or GitHub's **Use this template**. `pik new` removes that section from the project it creates.
- `POST /v1/sessions` takes `delivery: "cookie"`, which sets the session in an `HttpOnly`, `Secure`, `SameSite=Strict` `__Host-session` cookie and leaves `token` out of the body, for browser apps on the same origin as the API. `delivery` defaults to `body`, which works as before.
- Authenticated routes accept the `__Host-session` cookie when there's no `Authorization` header. An invalid or expired cookie gets 401 and is cleared, and logout always clears it. OpenAPI documents it as the `cookieAuth` scheme, and the bearer scheme is renamed `bearerAuth`.
- The `forbidden` problem type, with status 403.

### Changed

- `SESSION_TTL_HOURS` is capped at 9600 (400 days), the longest a browser keeps a cookie, instead of 8760. The API refuses to start above it.

### Security

- Requests to `/v1` that change data are checked for cross-origin browser requests, the same way as Go's `CrossOriginProtection`. Bearer clients are unaffected, but cross-site browser requests that change data now get 403 `forbidden` unless their origin is in `CORS_ORIGINS`.

## [0.2.0] - 2026-11-09

### Added

- A dev container with Postgres, migrations, seed data, `jq`, and `TEST_DATABASE_URL`, so `make verify` runs inside it.
- `scripts/check-migrations.sh`, run by `make verify` and CI, which fails when a committed migration is changed, renamed, or deleted.
- A test that fails when `docs/errors.md` and the problem catalog list different types.
- Migration `0002`, which indexes `sessions.user_id`, so deleting a user doesn't scan every session. On a large `sessions` table, build it concurrently first, as `docs/operations.md` explains.
- `DATABASE_POOL_MAX`, the API's database pool size. It defaults to 10, as before.

### Changed

- **Breaking:** `TRUST_PROXY` is replaced by `TRUST_PROXY_HOPS`, the number of proxies that append to `X-Forwarded-For`. `0`, the default, ignores the header. Set `TRUST_PROXY_HOPS=1` for the old `TRUST_PROXY=true`. The API refuses to start while `TRUST_PROXY` is set, and it falls back to the socket address when the chosen entry isn't an IP address.
- `DbSession` and `get_session` moved from `app.db` to `app.dependencies`, so jobs no longer load FastAPI through `app.db`. Update imports in your features.
- `tests/unit/test_architecture.py` finds every feature on its own and checks that jobs never load FastAPI, even indirectly. Ruff now bans relative imports.
- The agent harness is v0.3.0. Its check also fails when the harness workflow or pre-commit hook is missing or no longer runs the check.
- `renovate.json` belongs to the project and extends the shared baseline preset. Generated projects extend only `config:recommended`.

### Fixed

- The release workflow runs lint and tests before it publishes the image.
- CORS responses expose `ETag`, `Location`, `X-Request-Id`, `Retry-After`, the `RateLimit-*` headers, and `Idempotency-Replayed` to browser scripts. Only the preflight listed some of them before, where browsers ignore it.
- An expired `Idempotency-Key` creates a new note instead of replaying the old one, as it did until the hourly cleanup removed it.
- Idempotency keys are scoped to the endpoint as well as the user, so an endpoint that adds idempotency can't replay another's response. Migration `0003` changes the key's unique constraint. Idempotent `POST /v1/notes` requests on the old version fail until the new version is rolled out, so deploy both together.
- `LOG_LEVEL=warn`, as documented, no longer stops the API from starting. `warning` still works.
- Registration queues the welcome email in the same transaction as the user. A queueing failure used to return 500 but keep the user, so a retry got 409 and no email ever went out.
- Jobs and `seed` read their settings through `Settings` when they start, not from `os.environ` when `app.jobs` is imported. Jobs get the database from `context.additional_context`, and the API no longer opens a queue pool.
- Password hashing and checks run in a thread, so registration and login no longer block other requests.
- Migration `0001` creates procrastinate's tables from a frozen copy of its 3.10.0 schema instead of the installed package, so upgrading procrastinate no longer changes what `0001` does. The SQL is identical, and a test fails when the installed procrastinate is ahead of the migrations.

### Removed

- The unused `ProblemError.status` property. Read the status from `CATALOG` instead.

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
