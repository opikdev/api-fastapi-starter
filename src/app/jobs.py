"""Background jobs on Postgres, with procrastinate. Run them with `api-fastapi-starter worker`."""

import logging
from typing import Any
from uuid import UUID

import procrastinate
from procrastinate.tasks import Task
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import Settings, database_url, load_settings
from app.db import IdempotencyKey, RateLimit, Session, User, create_engine
from app.email import EmailSender, LogEmailSender

logger = logging.getLogger("app.jobs")

sender: EmailSender = LogEmailSender()


def conninfo(url: str) -> str:
    """psycopg wants a plain postgresql:// URL, not SQLAlchemy's driver form."""
    return database_url(url).replace("postgresql+psycopg://", "postgresql://", 1)


def _pool(**options: Any) -> AsyncConnectionPool:
    """Reads DATABASE_URL when the queue opens, not when this module is imported."""
    return AsyncConnectionPool(conninfo(str(load_settings().database_url)), **options)


queue = procrastinate.App(connector=procrastinate.PsycopgConnector(pool_factory=_pool))


async def defer(session: AsyncSession, task: Task[..., Any, ...], **arguments: Any) -> None:
    """Queues a job in the session's transaction, so it exists only if the transaction commits."""
    connection = await (await session.connection()).get_raw_connection()
    await task.configure(connection=connection.driver_connection).defer_async(**arguments)


async def run_worker(settings: Settings, **options: Any) -> None:
    """Runs jobs until the worker stops. Jobs share one engine, from `context.additional_context`."""
    engine = create_engine(
        str(settings.database_url),
        settings.database_statement_timeout_ms,
        settings.database_pool_max,
    )
    try:
        async with queue.open_async():
            await queue.run_worker_async(additional_context={"engine": engine}, **options)
    finally:
        await engine.dispose()


def job_engine(context: procrastinate.JobContext) -> AsyncEngine:
    engine: AsyncEngine = context.additional_context["engine"]
    return engine


@queue.task(
    name="send_welcome_email",
    pass_context=True,
    retry=procrastinate.RetryStrategy(max_attempts=5, exponential_wait=2),
)
async def send_welcome_email(context: procrastinate.JobContext, user_id: str) -> None:
    async with job_engine(context).connect() as connection:
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
@queue.task(name="delete_expired_rows", queueing_lock="delete_expired_rows", pass_context=True)
async def delete_expired_rows_hourly(context: procrastinate.JobContext, timestamp: int) -> None:
    await delete_expired_rows(job_engine(context))
    logger.info("Deleted expired rows")
