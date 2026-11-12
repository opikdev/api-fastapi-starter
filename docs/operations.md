# Operate the API

## Configure it

Set these on the API process. `.env.example` lists every option with a safe default. The API refuses to start if a value is invalid, and names the variable without echoing it.

| Variable | Type | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | URL | Required | Connection for the `api_app` role |
| `MIGRATION_DATABASE_URL` | URL | Required for `migrate` | Connection for the `api_owner` role |
| `PORT` | number | `3000` | Listen port |
| `LOG_LEVEL` | string | `info` | `debug`, `info`, `warn`, `warning`, or `error`. `warn` and `warning` are the same |
| `DATABASE_STATEMENT_TIMEOUT_MS` | number | `5000` | Cancels slow queries |
| `DATABASE_POOL_MAX` | number | `10` | Database connections per process. Keep the total across processes under Postgres's `max_connections` |
| `CORS_ORIGINS` | list | Empty | Comma-separated browser origins. They may call the API cross-origin, including requests that change data. Empty disables CORS |
| `TRUST_PROXY_HOPS` | number | `0` | How many proxies in front of the API append to `X-Forwarded-For`. `0` ignores the header and uses the socket address |
| `SESSION_TTL_HOURS` | number | `168` | Session lifetime, up to `9600` (400 days), the longest a browser keeps a cookie |
| `RATE_LIMIT_PER_MINUTE` | number | `300` | Per client, across `/v1` |
| `AUTH_RATE_LIMIT_PER_MINUTE` | number | `10` | Per client, on registration and login |
| `LOGIN_FAILURE_LIMIT` | number | `5` | Failed logins per email before login is locked for the rest of the window |
| `LOGIN_FAILURE_WINDOW_SECONDS` | number | `900` | Window for `LOGIN_FAILURE_LIMIT` |
| `SHUTDOWN_DRAIN_SECONDS` | number | `5` | On `SIGTERM`, how long `/readyz` fails while the API keeps serving. `0` skips the drain |
| `SHUTDOWN_TIMEOUT_SECONDS` | number | `30` | How long in-flight requests, or the worker's running jobs, get to finish. At least `DATABASE_STATEMENT_TIMEOUT_MS`, or the API refuses to start |
| `KEEP_ALIVE_TIMEOUT_SECONDS` | number | `75` | How long an idle connection stays open. Keep it above the load balancer's idle timeout |
| `DOCS_ENABLED` | boolean | `false` | Serves `/docs` and `/openapi.json`. `.env.example` and Compose set it to `true` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | URL | Empty | Turns on trace, metric, and error export. Other `OTEL_*` variables, such as `OTEL_EXPORTER_OTLP_HEADERS`, apply too |
| `OTEL_METRIC_EXPORT_INTERVAL` | number | `60000` | Milliseconds between metric exports |
| `APP_ENV` | string | Empty | Set to `production` to stop `seed` from adding demo data |
| `SEED_DEMO_DATA` | boolean | `false` | Set to `true` to let `seed` run when `APP_ENV` is `production` |
| `POSTGRES_PORT` | number | `5432` | Host port for Compose's Postgres. `.env.example` uses it in both database URLs, so `make` targets follow it. The API never reads it |

The worker reads `DATABASE_URL`, `LOG_LEVEL`, `DATABASE_STATEMENT_TIMEOUT_MS`, `DATABASE_POOL_MAX`, `SHUTDOWN_TIMEOUT_SECONDS`, and the `OTEL_*` variables too. `seed` reads `MIGRATION_DATABASE_URL` or `DATABASE_URL`, `APP_ENV`, and `SEED_DEMO_DATA`.

Set `TRUST_PROXY_HOPS` to the number of proxies you run, such as `1` behind one load balancer. Too low, and every client behind it shares one rate limit. Too high, and clients can forge `X-Forwarded-For` to dodge it. The API takes the address that many entries from the right, the leftmost if there are fewer, and the socket address if that entry isn't an IP address. `TRUST_PROXY` was replaced by it, and the API refuses to start while `TRUST_PROXY` is set.

## Read the rate limits

| Limit | Policy name | Key | Applies to |
|---|---|---|---|
| `RATE_LIMIT_PER_MINUTE` | `global` | Client network | Every `/v1` request |
| `AUTH_RATE_LIMIT_PER_MINUTE` | `auth` | Client network | `POST /v1/users` and `POST /v1/sessions` |
| `LOGIN_FAILURE_LIMIT` | `login` | SHA-256 of the email | Failed `POST /v1/sessions` |

The client network is the IPv4 address, or the /64 prefix of an IPv6 address, written like `2001:db8:1:2::/64`. An IPv4-mapped IPv6 address counts as IPv4. Counts live in Postgres, so every instance shares them.

Every `/v1` response describes its limits with the fields of [draft-ietf-httpapi-ratelimit-headers](https://datatracker.ietf.org/doc/draft-ietf-httpapi-ratelimit-headers/):

```http
RateLimit-Policy: "global";q=300;w=60, "auth";q=10;w=60
RateLimit: "global";r=238;t=25, "auth";r=9;t=55
```

`q` is the quota per window of `w` seconds, `r` what remains, and `t` the seconds until the window resets. On a 429, `RateLimit` and `Retry-After` describe only the limit that was exceeded. The `login` policy appears only on its own 429, so other responses never reveal it. Login checks it before the password, and counts only failed logins, so a correct password can't get through a locked email until the window ends. See [ADR 008](decisions/008-key-rate-limits-by-network-and-account.md).

## Deploy

Follow [Go live](deploy.md) for TLS, Postgres, roles and secrets, migrations, draining, docs, and telemetry. Run at least one worker, or jobs wait in the queue. Workers scale out, because Postgres hands each job to one worker.

## Change the schema safely

Treat migrations as append-only and forward-only. `scripts/check-migrations.sh`, part of `make verify` and CI, fails when a revision that's on `main` was changed, renamed, or deleted. Each Alembic revision has a `downgrade` for local use, but in production, undo a change with a new migration, or restore from a backup if data was lost.

- Create a revision with `make migration name="<what changed>"`. It numbers revisions in order, such as `0005`, autogenerates the change from `src/app/db.py`, then runs Ruff on the file. A test fails when a revision breaks the sequence.
- `migrate` holds an advisory lock, so concurrent runs apply each revision once, and sets `lock_timeout` to 5 seconds, so DDL fails fast instead of queueing every query behind it. Retry a timed-out run when traffic is lower.
- Rename or retype a column in steps: add the new one, backfill, switch the code, then drop the old one in a later deploy.
- Use `CREATE INDEX CONCURRENTLY` on large tables, so writes keep flowing while the index builds. In a migration, wrap `op.create_index(..., postgresql_concurrently=True)` in `with op.get_context().autocommit_block():`, because it can't run inside a transaction.
- The starter's own index migrations, such as `0002` for `idx_sessions_user_id`, build normally and lock writes to the table while they run. That's instant on a new project. If the table is already large, build the index first as the owner role, and the migration then skips it:

  ```sql
  CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sessions_user_id ON sessions (user_id);
  ```
- Migration `0001` creates procrastinate's tables from a frozen copy of its 3.10.0 schema, `0001_procrastinate_3.10.0.sql`, so it means the same thing on every install. When you upgrade procrastinate, add a revision that runs its upgrade scripts for each version in between, in order, from the folder `uv run procrastinate schema --migrations-path` prints. Run `pre` scripts before the new code deploys and `post` scripts after, as its release notes say. Revision `0004` is an example, for 3.11.0. Then bump `MIGRATED_TO` in `tests/unit/test_migrations.py`, which fails until you do.
- Read the SQL before merging, because a small diff can take a long lock.

## Back up the database

Use your provider's point-in-time recovery. For a self-hosted database, schedule `pg_dump` and copy the output off the host:

```sh
pg_dump --format=custom --file=api.dump "$MIGRATION_DATABASE_URL"
```

Restore into a new database, then point the API at it, so a bad backup can't overwrite good data:

```sh
pg_restore --no-owner --dbname="$NEW_DATABASE_URL" api.dump
```

Test a restore regularly, because an untested backup isn't a backup.

## Trace requests, jobs, and errors

Set `OTEL_EXPORTER_OTLP_ENDPOINT` to send traces and metrics to any OTLP/HTTP backend, from both the API and the worker.

- **Requests:** each gets a span named after its route, such as `GET /v1/notes/{note_id}`, with its database queries nested inside. `/healthz` and `/readyz` aren't traced, and log at `debug`, so probes don't bury real traffic.
- **Jobs:** each gets a span named `job <task name>`, such as `job send_welcome_email`, with its queries nested inside.
- **Errors:** unexpected errors are recorded on the span, so backends with error tracking can group them.
- **Logs:** each JSON log line written during a request or job has `trace_id` and `span_id`, so you can jump from a log line to its trace.
- **Metrics:** HTTP server duration and active requests from the instrumentation, and `db.client.connections.usage` for the database pool, every `OTEL_METRIC_EXPORT_INTERVAL` milliseconds.
