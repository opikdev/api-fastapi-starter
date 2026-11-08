import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from app import jobs
from app.config import database_url
from tests.conftest import ROOT, Database
from tests.helpers import api

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "statement",
    [
        "create table hacked (id int)",
        "drop table notes",
        "alter table users add column is_admin boolean",
        "truncate users",
    ],
)
async def test_the_app_role_cannot_change_the_schema(database: Database, statement: str) -> None:
    async with await psycopg.AsyncConnection.connect(database.app_url, autocommit=True) as app:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await app.execute(statement)


@pytest.mark.parametrize(
    "statement",
    [
        "insert into users (email, password_hash) values ('UPPER@example.com', 'x')",
        "insert into notes (user_id, title) values (uuidv7(), 'orphan')",
        "insert into notes (user_id, title) select id, '' from users limit 1",
        "update notes set version = 0",
    ],
)
async def test_the_database_rejects_invalid_rows_even_if_the_api_were_bypassed(
    database: Database, owner: psycopg.AsyncConnection, statement: str
) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        await user.create_note()
    with pytest.raises(psycopg.errors.IntegrityError):
        await owner.execute(statement)


async def test_deleting_a_user_removes_their_data(
    database: Database, owner: psycopg.AsyncConnection
) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        await user.create_note()
    await owner.execute("delete from users where email = %s", [user.email])
    for table in ("notes", "sessions"):
        orphans = await (
            await owner.execute(
                f"select count(*) from {table} where user_id not in (select id from users)"  # noqa: S608
            )
        ).fetchone()
        assert orphans == (0,)


async def test_constraints_follow_the_naming_convention(owner: psycopg.AsyncConnection) -> None:
    rows = await (
        await owner.execute(
            "select conname from pg_constraint join pg_class on pg_class.oid = conrelid "
            "where connamespace = 'public'::regnamespace and contype <> 'n' "
            "and relname not like 'procrastinate%' and relname <> 'alembic_version'"
        )
    ).fetchall()
    names = [row[0] for row in rows]
    assert names
    assert all(name.startswith(("pk_", "uq_", "fk_", "chk_")) for name in names), names


async def test_the_models_and_migrations_agree(database: Database) -> None:
    config = Config()
    config.set_main_option("script_location", str(ROOT / "src/app/migrations"))
    config.set_main_option("sqlalchemy.url", database.owner_url)
    command.check(config)


async def test_cleanup_deletes_only_expired_rows(
    database: Database, owner: psycopg.AsyncConnection
) -> None:
    async with api(database) as client:
        user = await client.sign_up()
    await owner.execute(
        "insert into rate_limits (key, reset_at) values ('old', now() - interval '1 minute'), "
        "('new', now() + interval '1 minute') on conflict do nothing"
    )
    await owner.execute(
        "update sessions set expires_at = now() - interval '1 second' "
        "where user_id = (select id from users where email = %s)",
        [user.email],
    )
    engine = create_async_engine(database_url(database.app_url))
    await jobs.delete_expired_rows(engine)
    await engine.dispose()
    keys = {row[0] for row in await (await owner.execute("select key from rate_limits")).fetchall()}
    assert "old" not in keys
    assert "new" in keys
    sessions = await (
        await owner.execute(
            "select count(*) from sessions where user_id = (select id from users where email = %s)",
            [user.email],
        )
    ).fetchone()
    assert sessions == (0,)
