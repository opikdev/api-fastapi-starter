# Customize the starter

## Rename the project

Projects created with `pik new` are already renamed. To rename a clone by hand, replace the text under each `from` in `pik.yaml`, in the files listed below it. Then replace the database names in `compose.yaml`, `.env.example`, and `docker/postgres/init.sql`. The import package stays `app` in every project, as [ADR 006](decisions/006-keep-a-fixed-import-package-name.md) explains.

## Add a feature

Copy the shape of `notes`:

1. Add a table to `src/app/db.py`, with a `uuidv7()` primary key and a `user_id` foreign key.
2. Autogenerate a migration, read it, then apply it:

   ```sh
   uv run --env-file .env alembic revision --autogenerate -m "add projects"
   make migrate
   ```

3. Create `src/app/features/projects/routes.py` with an `APIRouter`, request and response models built on `ApiModel`, and `responses=` for each problem it returns. Filter every query by the caller's user ID.
4. Include the router in `create_app` in `src/app/main.py`.
5. Add tests next to `tests/integration/test_notes.py`.
6. Run `make client`, then `make verify`, and commit `openapi.json` and `clients/python` too.

To put the stricter auth rate limit on a route, add `dependencies=[Depends(auth_rate_limit)]`.

## Remove the notes feature

1. Delete `src/app/features/notes/` and `tests/integration/test_notes.py`, and remove the router from `src/app/main.py`.
2. Remove `Note` from `src/app/db.py` and `src/app/seed.py`, then autogenerate a migration that drops the table.
3. Remove the note steps from `tests/e2e/test_stack.py`.
4. Run `make client`, then `make verify`.

## Remove idempotency

Remove the `idempotency_key` header from `create_note`, insert the note directly, and delete `create_idempotently`. Then remove `IdempotencyKey` from `src/app/db.py` and `delete_expired_rows`, and autogenerate a migration.

## Remove background jobs

Delete `src/app/jobs.py`, `src/app/email.py`, and `tests/integration/test_jobs.py`. Remove the `defer_async` call from registration, the queue from the lifespan in `src/app/main.py`, the `worker` command, and the `worker` service in Compose. Then drop procrastinate's tables in a new migration, and run `uv remove procrastinate`.

## Remove tracing

Delete `src/app/telemetry.py` and its call in `src/app/main.py`, then run `uv remove` for the `opentelemetry-*` packages. Error logging keeps working.
