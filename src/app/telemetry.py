"""OpenTelemetry traces, sent over OTLP/HTTP when OTEL_EXPORTER_OTLP_ENDPOINT is set."""

import os

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from sqlalchemy.ext.asyncio import AsyncEngine

SERVICE_NAME = "api-fastapi-starter"


def start_tracing(
    app: FastAPI, engine: AsyncEngine, processor: SpanProcessor | None = None
) -> TracerProvider | None:
    """Traces each request, named after its route, with its database queries nested inside."""
    if processor is None:
        if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
            return None
        exporter: SpanExporter = OTLPSpanExporter()
        processor = BatchSpanProcessor(exporter)
    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(
        app, tracer_provider=provider, exclude_spans=["receive", "send"]
    )
    # The instrumentation declares support up to SQLAlchemy 2.0 but works with 2.1, so skip its
    # version check. tests/integration/test_telemetry.py fails if database spans ever stop.
    SQLAlchemyInstrumentor().instrument(
        engine=engine.sync_engine, tracer_provider=provider, skip_dep_check=True
    )
    return provider
