# Operate the API

## Configure it

Set these on the API process. `.env.example` lists every option with a safe default. The API refuses to start if a value is invalid, and names the variable without echoing it.

| Variable | Type | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | URL | Required | Connection for the `api_app` role |
| `MIGRATION_DATABASE_URL` | URL | Required for `migrate` | Connection for the `api_owner` role |
| `PORT` | number | `3000` | Listen port |
| `LOG_LEVEL` | string | `info` | `debug`, `info`, `warn`, or `error` |
| `DATABASE_STATEMENT_TIMEOUT_MS` | number | `5000` | Cancels slow queries |
| `CORS_ORIGINS` | list | Empty | Comma-separated browser origins. Empty disables CORS |
| `TRUST_PROXY` | boolean | `false` | Set to `true` only behind a proxy that appends to `X-Forwarded-For` |
| `SESSION_TTL_HOURS` | number | `168` | Session lifetime |
| `RATE_LIMIT_PER_MINUTE` | number | `300` | Per client, across `/v1` |
| `AUTH_RATE_LIMIT_PER_MINUTE` | number | `10` | Per client, on registration and login |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | URL | Empty | Turns on trace and error export |
| `APP_ENV` | string | Empty | Set to `production` to stop `seed` from adding demo data |

The worker reads `DATABASE_URL` and `LOG_LEVEL` too.

Set `TRUST_PROXY` correctly, or every client behind a load balancer shares one rate limit.

## Set up production roles

Replace the dev passwords in `docker/postgres/init.sql`. Run the file once as the role that owns the schema, so tables created by migrations are granted to `api_app`.

## Deploy

Pushing a `vX.Y.Z` tag publishes an image for amd64 and arm64 to `ghcr.io`. The image's entry point runs every step, so deploy in this order:

1. Run the image with the `migrate` command and `MIGRATION_DATABASE_URL` set to the owner role.
2. Roll out the new image with `DATABASE_URL` set to `api_app`, for both the API and the `worker` command.
3. Send traffic when `GET /readyz` returns 200.

Run at least one worker, or jobs wait in the queue. Workers scale out, because Postgres hands each job to one worker.

Use `/healthz` for liveness, or the image's built-in `HEALTHCHECK`. It stays 200 during a database outage, so restarts don't make an outage worse. On `SIGTERM`, the API stops taking connections and finishes in-flight requests before it exits, and the worker finishes its current jobs.

## Change the schema safely

Treat migrations as append-only and forward-only. Each Alembic revision has a `downgrade` for local use, but in production, undo a change with a new migration, or restore from a backup if data was lost.

- Rename or retype a column in steps: add the new one, backfill, switch the code, then drop the old one in a later deploy.
- Use `CREATE INDEX CONCURRENTLY` on large tables, inside `op.get_context().autocommit_block()`.
- Migration `0001` creates procrastinate's tables from a frozen copy of its 3.10.0 schema, `0001_procrastinate_3.10.0.sql`, so it means the same thing on every install. When you upgrade procrastinate, add a revision that runs its upgrade scripts for each version in between, in order, from the folder `uv run procrastinate schema --migrations-path` prints. Run `pre` scripts before the new code deploys and `post` scripts after, as its release notes say. Then bump `MIGRATED_TO` in `tests/unit/test_migrations.py`, which fails until you do.
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

## Trace requests and errors

Set `OTEL_EXPORTER_OTLP_ENDPOINT` to send traces to any OTLP/HTTP backend. Each request gets a span named after its route, such as `GET /v1/notes/{note_id}`, with its database queries nested inside. Unexpected errors are recorded on the span, so backends with error tracking can group them.
