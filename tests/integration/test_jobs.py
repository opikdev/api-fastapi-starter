"""Runs real jobs through procrastinate on Postgres, as the worker process does."""

import os
from typing import Any

import httpx2
import psycopg
import pytest
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from procrastinate.testing import InMemoryConnector

from app import jobs
from app.db import create_engine
from app.main import create_app
from tests.conftest import Database
from tests.helpers import PASSWORD, api, assert_problem, settings

pytestmark = pytest.mark.anyio


class RecordingSender:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(self, *, to: str, subject: str, text: str) -> None:
        self.sent.append({"to": to, "subject": subject})


@pytest.fixture
def real_queue(database: Database, monkeypatch: pytest.MonkeyPatch) -> RecordingSender:
    monkeypatch.setenv("DATABASE_URL", database.app_url)
    sender = RecordingSender()
    monkeypatch.setattr(jobs, "sender", sender)
    return sender


async def test_the_worker_sends_a_welcome_email_after_registration(
    database: Database, real_queue: RecordingSender, owner: psycopg.AsyncConnection
) -> None:
    engine = create_engine(database.app_url)
    app = create_app(settings(database), engine=engine)
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        address = f"welcome-{os.urandom(4).hex()}@example.com"
        response = await http.post("/v1/users", json={"email": address, "password": PASSWORD})
        assert response.status_code == 201
    await engine.dispose()
    # The app role runs the worker, as in production, then it stops once the queue is empty.
    await jobs.run_worker(settings(database), wait=False, install_signal_handlers=False)
    assert {"to": address, "subject": "Welcome"} in real_queue.sent
    status = await (
        await owner.execute(
            "select status from procrastinate_jobs where task_name = 'send_welcome_email' "
            "order by id desc limit 1"
        )
    ).fetchone()
    assert status == ("succeeded",)


async def test_the_cleanup_runs_every_hour() -> None:
    schedules = {
        periodic.task.name: periodic.cron
        for periodic in jobs.queue.periodic_registry.periodic_tasks.values()
    }
    assert schedules == {"delete_expired_rows": "7 * * * *", "retry_stalled_jobs": "*/5 * * * *"}


async def test_retries_a_job_left_running_by_a_worker_that_died(
    database: Database, real_queue: RecordingSender, owner: psycopg.AsyncConnection
) -> None:
    await owner.execute("delete from procrastinate_jobs")
    dead = await (
        await owner.execute(
            "insert into procrastinate_workers (last_heartbeat) "
            "values (now() - interval '10 minutes') returning id"
        )
    ).fetchone()
    alive = await (
        await owner.execute("insert into procrastinate_workers default values returning id")
    ).fetchone()
    assert dead is not None
    assert alive is not None
    for worker_id, user_id in ((dead[0], "stalled"), (alive[0], "running")):
        await owner.execute(
            "insert into procrastinate_jobs (queue_name, task_name, args, status, worker_id) "
            "values ('default', 'send_welcome_email', %s, 'doing', %s)",
            [f'{{"user_id": "{user_id}"}}', worker_id],
        )
    async with jobs.queue.open_async():
        retried = await jobs.retry_stalled(jobs.queue.job_manager)
    statuses = await (
        await owner.execute(
            "select args->>'user_id', status from procrastinate_jobs order by args->>'user_id'"
        )
    ).fetchall()
    assert retried == 1
    assert statuses == [("running", "doing"), ("stalled", "todo")]


async def test_the_worker_traces_each_job(
    database: Database, real_queue: RecordingSender, owner: psycopg.AsyncConnection
) -> None:
    await owner.execute("delete from procrastinate_jobs")
    async with jobs.queue.open_async():
        await jobs.send_welcome_email.defer_async(user_id="00000000-0000-0000-0000-000000000000")
    spans = InMemorySpanExporter()
    await jobs.run_worker(
        settings(database),
        span_processor=SimpleSpanProcessor(spans),
        wait=False,
        install_signal_handlers=False,
    )
    finished = spans.get_finished_spans()
    job = next(span for span in finished if span.name == "job send_welcome_email")
    assert job.attributes is not None
    assert job.attributes["messaging.system"] == "procrastinate"
    assert any(
        span.context.trace_id == job.context.trace_id
        and span.attributes
        and "db.statement" in span.attributes
        for span in finished
    )


class BrokenQueue(InMemoryConnector):
    async def defer_jobs_all(self, jobs: list[Any]) -> list[Any]:
        raise RuntimeError("the queue is down")


async def test_registration_saves_nothing_when_the_welcome_email_cannot_be_queued(
    database: Database, owner: psycopg.AsyncConnection
) -> None:
    address = f"atomic-{os.urandom(4).hex()}@example.com"
    credentials = {"email": address, "password": PASSWORD}
    async with api(database, BrokenQueue()) as client:
        failed = await client.http.post("/v1/users", json=credentials)
    assert_problem(failed, 500, "internal-error")
    users = await owner.execute("select count(*) from users where email = %s", [address])
    assert await users.fetchone() == (0,)
    async with api(database) as client:
        retried = await client.http.post("/v1/users", json=credentials)
        assert retried.status_code == 201
        assert [job["task_name"] for job in client.jobs.jobs.values()] == ["send_welcome_email"]
