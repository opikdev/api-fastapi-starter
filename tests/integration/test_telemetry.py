import contextlib
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx2
import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import database_url
from app.log import JsonFormatter
from app.main import create_app
from tests.conftest import Database
from tests.helpers import settings

pytestmark = pytest.mark.anyio


@dataclass
class Traced:
    http: httpx2.AsyncClient
    spans: InMemorySpanExporter
    metrics: InMemoryMetricReader


@contextlib.asynccontextmanager
async def traced(database: Database, engine: AsyncEngine | None = None) -> AsyncIterator[Traced]:
    """Runs the app with in-memory exporters, and its lifespan, which flushes them at the end."""
    spans, metrics = InMemorySpanExporter(), InMemoryMetricReader()
    engine = engine or create_async_engine(database_url(database.app_url))
    app = create_app(
        settings(database),
        engine=engine,
        span_processor=SimpleSpanProcessor(spans),
        metric_reader=metrics,
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as http,
    ):
        yield Traced(http, spans, metrics)


async def test_traces_requests_by_route_with_database_spans_inside(database: Database) -> None:
    async with traced(database) as app:
        await app.http.get(
            "/v1/notes/note_00000000000000000000000000000000", headers={"Authorization": "Bearer x"}
        )
        finished = app.spans.get_finished_spans()
    request = next(span for span in finished if span.name == "GET /v1/notes/{note_id}")
    database_spans = [
        span for span in finished if span.attributes and "db.statement" in span.attributes
    ]
    assert any(span.context.trace_id == request.context.trace_id for span in database_spans)


async def test_never_traces_health_checks(database: Database) -> None:
    async with traced(database) as app:
        await app.http.get("/healthz")
        await app.http.get("/readyz")
        assert app.spans.get_finished_spans() == ()


class JsonLines(logging.Handler):
    """Formats each record as it's logged, while its span is still current."""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.setFormatter(JsonFormatter())
        self.entries: list[dict[str, object]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.entries.append(json.loads(self.format(record)))


async def test_logs_the_trace_and_span_of_the_request(database: Database) -> None:
    lines, logger = JsonLines(), logging.getLogger("app.http")
    logger.addHandler(lines)
    previous = logger.level
    logger.setLevel(logging.INFO)
    try:
        async with traced(database) as app:
            await app.http.get("/v1/users/me")
            request = next(
                span for span in app.spans.get_finished_spans() if span.name == "GET /v1/users/me"
            )
    finally:
        logger.removeHandler(lines)
        logger.setLevel(previous)
    entry = next(entry for entry in lines.entries if entry["msg"] == "Request completed")
    assert entry["trace_id"] == format(request.context.trace_id, "032x")
    assert len(str(entry["span_id"])) == 16


async def test_exports_http_and_database_pool_metrics(database: Database) -> None:
    async with traced(database) as app:
        await app.http.get("/v1/users/me")
        data = app.metrics.get_metrics_data()
    assert data is not None
    names = {
        metric.name
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
    }
    assert "http.server.duration" in names or "http.server.request.duration" in names, names
    assert "db.client.connections.usage" in names, names


async def test_records_an_unhandled_error_on_the_span(database: Database) -> None:
    broken = create_async_engine(
        database_url("postgresql://nobody:wrong@127.0.0.1:1/none"),
        connect_args={"connect_timeout": 1},
    )
    async with traced(database, broken) as app:
        response = await app.http.get("/v1/users/me", headers={"Authorization": "Bearer x"})
        errored = [
            span
            for span in app.spans.get_finished_spans()
            if span.status.status_code == StatusCode.ERROR
        ]
    assert response.status_code == 500
    assert any(event.name == "exception" for span in errored for event in span.events)
