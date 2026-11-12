# Go live

Work through this page before the API takes real traffic. Every setting is listed in [Operate the API](operations.md#configure-it).

## Get the image

Pushing a `vX.Y.Z` tag runs the same gates as CI: lint, types, tests, the migration check, and the end-to-end tests. Then it builds the image, scans it with Trivy, and fails on any fixable HIGH or CRITICAL finding before anything is pushed. Only then does it publish the image for amd64 and arm64 to `ghcr.io`, with an SBOM and a signed build provenance attestation. Verify the attestation before you deploy:

```sh
gh attestation verify oci://ghcr.io/<OWNER>/<REPO>:<VERSION> --owner <OWNER>
```

The image runs as a non-root user and works with a read-only root filesystem.

## Put it behind TLS

Terminate TLS at a load balancer or reverse proxy, and forward plain HTTP to the API's `PORT`.

- Set `TRUST_PROXY_HOPS` to the number of proxies that append to `X-Forwarded-For`, such as `1` behind one load balancer. Rate limits key on the client address it picks.
- The API sends `Strict-Transport-Security` with `includeSubDomains` on every response. Browsers only honor it over HTTPS, and then refuse plain HTTP for that host and its subdomains for 180 days, so serve the API over HTTPS only.
- Keep `KEEP_ALIVE_TIMEOUT_SECONDS` above the load balancer's idle timeout, such as AWS ALB's 60 seconds, or the API closes connections the balancer is about to reuse and clients see 502s.

## Connect to Postgres

- Use TLS and check the server's certificate: add `?sslmode=verify-full&sslrootcert=/run/secrets/db-ca.pem` to `DATABASE_URL` and `MIGRATION_DATABASE_URL`, and mount the provider's CA file there.
- Keep `DATABASE_POOL_MAX` × the number of API and worker processes below Postgres's `max_connections`, leaving room for migrations and admin sessions. For example, 8 processes × 10 needs `max_connections` above 80.
- With more processes than that allows, put PgBouncer in transaction mode in front of the API. psycopg works with it once you set PgBouncer's `max_prepared_statements`, available since 1.21. Connect the worker and `migrate` directly, because the worker uses `LISTEN` and migrations hold a session-level advisory lock.

## Set the roles and secrets

The API and worker connect as `api_app`, which can read and write rows but can't change the schema. Migrations run as the owner role, `api_owner` in development.

1. Create the owner role with your provider, and use it as `MIGRATION_DATABASE_URL`.
2. Run `docker/postgres/init.sql` once as that role, so tables that migrations create are granted to `api_app`. It creates `api_app` without a password.
3. Set the `api_app` password from your secret store, without writing it into a file:

   ```sh
   psql "$MIGRATION_DATABASE_URL" -v app_password="$APP_DB_PASSWORD" <<'SQL'
   ALTER ROLE api_app PASSWORD :'app_password';
   SQL
   ```

Inject `DATABASE_URL`, `MIGRATION_DATABASE_URL`, and `OTEL_EXPORTER_OTLP_HEADERS` from the platform's secret store, such as Kubernetes Secrets or AWS Secrets Manager. Never bake them into the image or commit them.

## Migrate once per deploy

Run the image with the `migrate` command as one job per deploy, such as a Kubernetes `Job` or a pre-deploy step, before the new version takes traffic. Then roll out the API and the `worker` command.

Migrations hold a Postgres advisory lock for the whole run, so a second `migrate` waits, then finds nothing to do. Running it in every replica's startup is safe too, just slower. DDL waits at most 5 seconds for a table lock, then fails instead of stalling live queries behind it. Rerun it at a quieter time.

## Drain on shutdown

On `SIGTERM`, the API fails `GET /readyz` with 503 but keeps serving for `SHUTDOWN_DRAIN_SECONDS`, so the load balancer stops sending new requests. Then it stops accepting connections, gives in-flight requests up to `SHUTDOWN_TIMEOUT_SECONDS`, and closes the database pool and telemetry exporters. `GET /healthz` stays 200 throughout. The worker stops taking jobs and gives running ones up to `SHUTDOWN_TIMEOUT_SECONDS`.

| Setting | Value |
|---|---|
| Readiness probe | `GET /readyz`, with period × failure threshold below `SHUTDOWN_DRAIN_SECONDS`, such as every 2 seconds with a threshold of 2 for the default 5 |
| Liveness probe | `GET /healthz`, or the image's `HEALTHCHECK` |
| Kubernetes `terminationGracePeriodSeconds` | Above `SHUTDOWN_DRAIN_SECONDS` + `SHUTDOWN_TIMEOUT_SECONDS`, such as `40` for the defaults. Compose sets `stop_grace_period: 40s` |
| Load balancer deregistration delay | `SHUTDOWN_TIMEOUT_SECONDS` or less, such as 30 seconds on an AWS target group, whose default is 300 |

## Keep the docs off

`DOCS_ENABLED` defaults to `false`, so `/docs` and `/openapi.json` return 404 in production. Leave it off, or turn it on knowingly, because the document maps every route. The committed `openapi.json` is the same document.

## Send telemetry

Set `OTEL_EXPORTER_OTLP_ENDPOINT` to an OTLP/HTTP collector to export traces and metrics from the API and the worker. The standard `OTEL_*` variables apply, such as `OTEL_EXPORTER_OTLP_HEADERS` for an API key and `OTEL_METRIC_EXPORT_INTERVAL` in milliseconds. See [Trace requests, jobs, and errors](operations.md#trace-requests-jobs-and-errors).

## Back up the database

Turn on your provider's point-in-time recovery. For a self-hosted database, see [Back up the database](operations.md#back-up-the-database).
