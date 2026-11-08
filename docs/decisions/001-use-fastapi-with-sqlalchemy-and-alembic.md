# 001. Use FastAPI with SQLAlchemy and Alembic

- **Status**: accepted
- **Context**: A Python API needs typed requests, an OpenAPI document that can't drift, and a mature data layer with migrations. The brief names FastAPI, SQLAlchemy, Alembic, and uv.
- **Decision**: Define routes and models in FastAPI and Pydantic, generate `openapi.json` and a Python client from them, and use async SQLAlchemy on psycopg 3 with Alembic migrations.
- **Consequences**:
  - The routes are the contract. A test fails if the committed `openapi.json` is stale, and CI fails if the client is.
  - `alembic check` in the tests catches models and migrations that disagree.
  - One driver, psycopg 3, serves SQLAlchemy and the job queue.
  - The OpenTelemetry SQLAlchemy instrumentation hasn't declared support for SQLAlchemy 2.1, so its version check is skipped, and a test guards the database spans.
