"""Runs migrations as the owner role, from MIGRATION_DATABASE_URL."""

import os

from alembic import context
from sqlalchemy import create_engine, text

from app.config import database_url
from app.db import Base

# Any fixed number works, as long as nothing else takes an advisory lock with it.
MIGRATION_LOCK = 7_310_456_218

url = context.config.get_main_option("sqlalchemy.url") or os.environ.get("MIGRATION_DATABASE_URL")
if not url:
    raise SystemExit("Set MIGRATION_DATABASE_URL to the owner role's connection, then retry.")


def include_object(
    item: object, name: str | None, kind: str, reflected: bool, compare_to: object
) -> bool:
    # Procrastinate owns its tables, so autogenerate and check ignore them.
    return not (
        kind in {"table", "index"}
        and (name or "").startswith(("procrastinate", "idx_procrastinate"))
    )


engine = create_engine(database_url(url))
with engine.connect() as connection:
    # A second run waits here until the first finishes, then finds nothing left to apply.
    connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK})
    # Fail fast instead of queueing behind live traffic, which would block every query after it.
    connection.execute(text("SET lock_timeout = '5s'"))
    connection.commit()
    try:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            compare_server_default=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()
    finally:
        connection.rollback()
        connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK})
        connection.commit()
engine.dispose()
