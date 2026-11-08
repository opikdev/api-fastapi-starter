import httpx2
import pytest
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import database_url
from app.main import create_app
from tests.conftest import Database
from tests.helpers import settings

pytestmark = pytest.mark.anyio


async def test_traces_requests_by_route_with_database_spans_inside(database: Database) -> None:
    spans = InMemorySpanExporter()
    engine = create_async_engine(database_url(database.app_url))
    app = create_app(settings(database), engine=engine, span_processor=SimpleSpanProcessor(spans))
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://test"
    ) as http:
        await http.get(
            "/v1/notes/note_00000000000000000000000000000000", headers={"Authorization": "Bearer x"}
        )
        await http.get("/readyz")
    await engine.dispose()
    finished = spans.get_finished_spans()
    names = [span.name for span in finished]
    assert "GET /v1/notes/{note_id}" in names
    assert "GET /readyz" in names
    database_spans = [
        span for span in finished if span.attributes and "db.statement" in span.attributes
    ]
    assert database_spans, f"no database spans in {names}"
    request = next(span for span in finished if span.name == "GET /readyz")
    assert any(span.context.trace_id == request.context.trace_id for span in database_spans)


async def test_records_an_unhandled_error_on_the_span(database: Database) -> None:
    spans = InMemorySpanExporter()
    broken = create_async_engine(
        database_url("postgresql://nobody:wrong@127.0.0.1:1/none"),
        connect_args={"connect_timeout": 1},
    )
    app = create_app(settings(database), engine=broken, span_processor=SimpleSpanProcessor(spans))
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://test"
    ) as http:
        response = await http.get("/v1/users/me", headers={"Authorization": "Bearer x"})
    await broken.dispose()
    assert response.status_code == 500
    errored = [
        span for span in spans.get_finished_spans() if span.status.status_code == StatusCode.ERROR
    ]
    assert any(event.name == "exception" for span in errored for event in span.events)
