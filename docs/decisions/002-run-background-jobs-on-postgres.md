# 002. Run background jobs on Postgres

- **Status**: accepted
- **Context**: The API needs background work, such as emails and cleanup, that survives restarts and retries on failure. Celery, RQ, and arq all need Redis or a broker, which would be a second service to run.
- **Decision**: Use procrastinate, which stores jobs in Postgres and wakes workers with `LISTEN`/`NOTIFY`. Create its schema in the first Alembic migration, from a frozen copy of procrastinate's SQL rather than the installed package, so that migration never changes.
- **Consequences**:
  - There's no new infrastructure, and jobs share the database's backups.
  - Workers scale out, because each job goes to exactly one worker.
  - Jobs are retried, so each one must be safe to run twice.
  - Upgrading procrastinate means applying its upgrade scripts in a new Alembic revision. A test fails when the installed version is ahead of the migrations.
  - Throughput is lower than a dedicated broker, so move very high-volume queues elsewhere if they appear.
