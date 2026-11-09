"""Runs real jobs through procrastinate on Postgres, as the worker process does."""

import os
from typing import Any

import httpx2
import psycopg
import pytest
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
    assert schedules == {"delete_expired_rows": "7 * * * *"}


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
