"""Background jobs on Postgres, with procrastinate. Run them with `api-fastapi-starter worker`."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import procrastinate
from opentelemetry.sdk.trace import SpanProcessor
from opentelemetry.trace import SpanKind, Tracer
from procrastinate.manager import JobManager
from procrastinate.tasks import Task
from procrastinate.worker import Worker
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import Settings, database_url, load_settings
from app.db import IdempotencyKey, RateLimit, Session, User, create_engine
from app.email import EmailSender, LogEmailSender
from app.telemetry import start_telemetry

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


def traced(tracer: Tracer) -> Callable[..., Awaitable[Any]]:
    """A worker middleware that runs each job in its own span, which records any error."""

    async def middleware(
        call_next: Callable[[], Awaitable[Any]], context: procrastinate.JobContext, worker: Worker
    ) -> Any:
        job = context.job
        attributes: dict[str, str | int] = {
            "messaging.system": "procrastinate",
            "messaging.destination.name": job.queue,
            "messaging.message.id": str(job.id),
            "procrastinate.job.attempts": job.attempts,
        }
        with tracer.start_as_current_span(
            f"job {job.task_name}", kind=SpanKind.CONSUMER, attributes=attributes
        ):
            return await call_next()

    return middleware


async def run_worker(
    settings: Settings, span_processor: SpanProcessor | None = None, **options: Any
) -> None:
    """Runs jobs until the worker stops. Jobs share one engine, from `context.additional_context`.

    On SIGTERM it stops taking jobs, and waits up to SHUTDOWN_TIMEOUT_SECONDS for running ones.
    """
    engine = create_engine(
        str(settings.database_url),
        settings.database_statement_timeout_ms,
        settings.database_pool_max,
    )
    telemetry = start_telemetry(engine, span_processor)
    if telemetry is not None:
        tracer = telemetry.tracer_provider.get_tracer(__name__)
        options.setdefault("worker_middleware", [traced(tracer)])
    try:
        async with queue.open_async():
            await queue.run_worker_async(
                additional_context={"engine": engine},
                shutdown_graceful_timeout=settings.shutdown_timeout_seconds,
                **options,
            )
    finally:
        await engine.dispose()
        if telemetry is not None:
            telemetry.shutdown()


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


async def retry_stalled(manager: JobManager) -> int:
    """Puts jobs back in the queue whose worker died mid-job, and returns how many."""
    stalled = list(await manager.get_stalled_jobs())
    for job in stalled:
        await manager.retry_job(job)
    return len(stalled)


@queue.periodic(cron="*/5 * * * *")
@queue.task(name="retry_stalled_jobs", queueing_lock="retry_stalled_jobs", pass_context=True)
async def retry_stalled_jobs(context: procrastinate.JobContext, timestamp: int) -> None:
    retried = await retry_stalled(context.app.job_manager)
    if retried:
        logger.warning("Retried jobs from a stopped worker", extra={"count": retried})
