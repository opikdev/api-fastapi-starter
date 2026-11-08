"""Background jobs on Postgres, with procrastinate. Run them with `api-fastapi-starter worker`."""

import functools
import logging
import os
from uuid import UUID

import procrastinate
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import database_url
from app.db import IdempotencyKey, RateLimit, Session, User, create_engine
from app.email import EmailSender, LogEmailSender

logger = logging.getLogger("app.jobs")

sender: EmailSender = LogEmailSender()


def conninfo(url: str) -> str:
    """psycopg wants a plain postgresql:// URL, not SQLAlchemy's driver form."""
    return database_url(url).replace("postgresql+psycopg://", "postgresql://", 1)


queue = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=conninfo(os.environ.get("DATABASE_URL", "")))
)


@functools.cache
def _engine(url: str) -> AsyncEngine:
    return create_engine(url)


async def close() -> None:
    """Closes the database connections jobs opened. The worker calls it when it stops."""
    if _engine.cache_info().currsize:
        await _engine(os.environ["DATABASE_URL"]).dispose()
        _engine.cache_clear()


@queue.task(
    name="send_welcome_email",
    retry=procrastinate.RetryStrategy(max_attempts=5, exponential_wait=2),
)
async def send_welcome_email(user_id: str) -> None:
    async with _engine(os.environ["DATABASE_URL"]).connect() as connection:
        email = (
            await connection.execute(select(User.email).where(User.id == UUID(user_id)))
        ).scalar_one_or_none()
    if email is not None:
        await sender.send(to=email, subject="Welcome", text="Your account is ready.")


async def delete_expired_rows(engine: AsyncEngine) -> None:
    """Removes expired sessions, idempotency keys, and rate-limit windows."""
    async with engine.begin() as connection:
        await connection.execute(delete(Session).where(Session.expires_at <= func.now()))
        await connection.execute(
            delete(IdempotencyKey).where(IdempotencyKey.expires_at <= func.now())
        )
        await connection.execute(delete(RateLimit).where(RateLimit.reset_at <= func.now()))


@queue.periodic(cron="7 * * * *")
@queue.task(name="delete_expired_rows", queueing_lock="delete_expired_rows")
async def delete_expired_rows_hourly(timestamp: int) -> None:
    await delete_expired_rows(_engine(os.environ["DATABASE_URL"]))
    logger.info("Deleted expired rows")
