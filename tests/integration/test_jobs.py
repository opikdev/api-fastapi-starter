"""Runs real jobs through procrastinate on Postgres, as the worker process does."""

import os

import httpx2
import procrastinate
import psycopg
import pytest

from app import jobs
from app.db import create_engine
from app.main import create_app
from tests.conftest import Database
from tests.helpers import PASSWORD, settings

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
    connector = procrastinate.PsycopgConnector(conninfo=jobs.conninfo(database.app_url))
    with jobs.queue.replace_connector(connector):
        async with jobs.queue.open_async():
            engine = create_engine(database.app_url)
            app = create_app(settings(database), engine=engine)
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
            ) as http:
                address = f"welcome-{os.urandom(4).hex()}@example.com"
                response = await http.post(
                    "/v1/users", json={"email": address, "password": PASSWORD}
                )
                assert response.status_code == 201
            # The app role runs the worker, as in production, then it stops once the queue is empty.
            await jobs.queue.run_worker_async(wait=False, install_signal_handlers=False)
            await jobs.close()
            await engine.dispose()
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
