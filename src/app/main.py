"""Builds the FastAPI app: middleware, error handlers, routes, and the OpenAPI document."""

import contextlib
from collections.abc import AsyncIterator
from importlib.metadata import version

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics.export import MetricReader
from opentelemetry.sdk.trace import SpanProcessor
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from starlette.exceptions import HTTPException

from app import docs, openapi
from app.config import Settings
from app.db import create_engine
from app.features.auth.routes import router as auth_router
from app.features.notes.routes import router as notes_router
from app.health import router as health_router
from app.middleware import Cors, CrossOrigin, GuardV1, HeadAsGet, RequestContext
from app.problems import INVALID_FIELDS, FieldError, ProblemError, Slug
from app.telemetry import start_telemetry

PROJECT = "api-fastapi-starter"
# Each class of constraint violation, by SQLSTATE, and the problem it becomes.
CONSTRAINT_PROBLEMS = {
    "23505": (
        Slug.CONFLICT,
        "The request conflicts with data that already exists. Change the conflicting value, "
        "then retry.",
    ),
    "23503": (
        Slug.CONFLICT,
        "The request refers to data that does not exist, or that other data still depends on.",
    ),
    "23514": (Slug.VALIDATION_FAILED, "A value is outside the allowed range. Fix it and retry."),
}


def _field_errors(error: RequestValidationError) -> list[FieldError]:
    fields = []
    for issue in error.errors():
        if issue["type"] == "json_invalid":
            fields.append(FieldError(field="", detail="isn't valid JSON"))
            continue
        location = [str(part) for part in issue["loc"]]
        # An empty field means the problem is with the whole body, not one field in it.
        field = ".".join(location[1:]) or ("" if location == ["body"] else location[0])
        fields.append(FieldError(field=field, detail=issue["msg"]))
    return fields


async def _problem(request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, ProblemError):
        raise error
    return error.response(request.url.path)


async def _invalid(request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, RequestValidationError):
        raise error
    problem = ProblemError(Slug.VALIDATION_FAILED, INVALID_FIELDS, _field_errors(error))
    return problem.response(request.url.path)


async def _http(request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, HTTPException):
        raise error
    headers = dict(error.headers or {})
    match error.status_code:
        case 404:
            problem = ProblemError(Slug.NOT_FOUND, "No route matches this path.")
        case 405:
            problem = ProblemError(
                Slug.METHOD_NOT_ALLOWED, "This path doesn't support that method.", headers=headers
            )
        case 400:
            problem = ProblemError(
                Slug.VALIDATION_FAILED,
                INVALID_FIELDS,
                [FieldError(field="", detail="couldn't be read")],
            )
        case _:
            raise error
    return problem.response(request.url.path)


async def _constraint(request: Request, error: Exception) -> JSONResponse:
    """Turns a constraint violation a route didn't handle into a problem that names no internals."""
    sqlstate = getattr(getattr(error, "orig", None), "sqlstate", None)
    if not isinstance(error, IntegrityError) or sqlstate not in CONSTRAINT_PROBLEMS:
        raise error
    slug, detail = CONSTRAINT_PROBLEMS[sqlstate]
    return ProblemError(slug, detail).response(request.url.path)


def create_app(
    settings: Settings,
    engine: AsyncEngine | None = None,
    span_processor: SpanProcessor | None = None,
    metric_reader: MetricReader | None = None,
) -> FastAPI:
    engine = engine or create_engine(
        str(settings.database_url),
        settings.database_statement_timeout_ms,
        settings.database_pool_max,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    telemetry = start_telemetry(engine, span_processor, metric_reader)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()
        if telemetry is not None:
            telemetry.shutdown()

    app = FastAPI(
        title=PROJECT,
        version=version(PROJECT),
        lifespan=lifespan,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        docs_url=None,
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=None,
    )
    app.state.settings = settings
    app.state.sessions = sessions
    app.state.draining = False
    app.openapi = lambda: openapi.build(app)  # type: ignore[method-assign]

    app.add_exception_handler(ProblemError, _problem)
    app.add_exception_handler(RequestValidationError, _invalid)
    app.add_exception_handler(HTTPException, _http)
    app.add_exception_handler(IntegrityError, _constraint)

    # Added innermost first: RequestContext ends up outermost, so it sees every response.
    app.add_middleware(CrossOrigin, origins=settings.origins)
    app.add_middleware(
        GuardV1,
        sessions=sessions,
        limit=settings.rate_limit_per_minute,
        proxy_hops=settings.trust_proxy_hops,
    )
    app.add_middleware(HeadAsGet)
    app.add_middleware(Cors, origins=settings.origins)
    app.add_middleware(RequestContext)

    if telemetry is not None:
        # Probes run every few seconds, so tracing them would bury real requests.
        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=telemetry.tracer_provider,
            meter_provider=telemetry.meter_provider,
            excluded_urls="/healthz$,/readyz$",
            exclude_spans=["receive", "send"],
        )
    if settings.docs_enabled:
        docs.mount(app)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(notes_router)
    return app
