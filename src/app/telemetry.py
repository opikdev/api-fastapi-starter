"""OpenTelemetry traces and metrics, sent over OTLP/HTTP when OTEL_EXPORTER_OTLP_ENDPOINT is set."""

import os
from dataclasses import dataclass

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from sqlalchemy.ext.asyncio import AsyncEngine

SERVICE_NAME = "api-fastapi-starter"


@dataclass(frozen=True)
class Telemetry:
    tracer_provider: TracerProvider
    meter_provider: MeterProvider

    def shutdown(self) -> None:
        """Flushes the spans and metrics still buffered, then stops exporting."""
        SQLAlchemyInstrumentor().uninstrument()
        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()


def start_telemetry(
    engine: AsyncEngine,
    span_processor: SpanProcessor | None = None,
    metric_reader: MetricReader | None = None,
) -> Telemetry | None:
    """Traces and measures database calls on `engine`. Returns None when nothing exports."""
    if span_processor is None:
        if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
            return None
        span_processor = BatchSpanProcessor(OTLPSpanExporter())
        metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter())
    resource = Resource.create({"service.name": SERVICE_NAME})
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(span_processor)
    trace.set_tracer_provider(tracer_provider)
    meter_provider = MeterProvider(
        resource=resource, metric_readers=[metric_reader] if metric_reader else []
    )
    # The instrumentation declares support up to SQLAlchemy 2.0 but works with 2.1, so skip its
    # version check. tests/integration/test_telemetry.py fails if database spans ever stop.
    SQLAlchemyInstrumentor().instrument(
        engine=engine.sync_engine,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        skip_dep_check=True,
    )
    return Telemetry(tracer_provider, meter_provider)
