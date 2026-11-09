"""Builds the FastAPI app: middleware, error handlers, routes, and the OpenAPI document."""

import contextlib
from collections.abc import AsyncIterator
from importlib.metadata import version
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from opentelemetry.sdk.trace import SpanProcessor
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from starlette.exceptions import HTTPException

from app.config import Settings
from app.db import create_engine
from app.features.auth.routes import router as auth_router
from app.features.notes.routes import router as notes_router
from app.health import router as health_router
from app.middleware import Cors, GuardV1, HeadAsGet, RequestContext
from app.problems import INVALID_FIELDS, FieldError, ProblemError, Slug
from app.telemetry import start_tracing

TITLE = "API FastAPI starter"


def _field_errors(error: RequestValidationError) -> list[FieldError]:
    fields = []
    for issue in error.errors():
        if issue["type"] == "json_invalid":
            fields.append(FieldError(field="body", detail="isn't valid JSON"))
            continue
        location = [str(part) for part in issue["loc"]]
        fields.append(FieldError(field=".".join(location[1:]) or location[0], detail=issue["msg"]))
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
                [FieldError(field="body", detail="couldn't be read")],
            )
        case _:
            raise error
    return problem.response(request.url.path)


def _openapi(app: FastAPI) -> dict[str, Any]:
    """FastAPI documents 422 for validation, but this API answers 400 Problem Details instead."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    for path in schema["paths"].values():
        for operation in path.values():
            operation.get("responses", {}).pop("422", None)
    for name in ("HTTPValidationError", "ValidationError"):
        schema.get("components", {}).get("schemas", {}).pop(name, None)
    app.openapi_schema = schema
    return schema


def create_app(
    settings: Settings,
    engine: AsyncEngine | None = None,
    span_processor: SpanProcessor | None = None,
) -> FastAPI:
    engine = engine or create_engine(
        str(settings.database_url),
        settings.database_statement_timeout_ms,
        settings.database_pool_max,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    provider = None

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()
        if provider is not None:
            provider.shutdown()

    app = FastAPI(
        title=TITLE,
        version=version("api-fastapi-starter"),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.sessions = sessions
    app.openapi = lambda: _openapi(app)  # type: ignore[method-assign]

    app.add_exception_handler(ProblemError, _problem)
    app.add_exception_handler(RequestValidationError, _invalid)
    app.add_exception_handler(HTTPException, _http)

    # Added innermost first: RequestContext ends up outermost, so it sees every response.
    app.add_middleware(
        GuardV1,
        sessions=sessions,
        limit=settings.rate_limit_per_minute,
        proxy_hops=settings.trust_proxy_hops,
    )
    app.add_middleware(HeadAsGet)
    app.add_middleware(Cors, origins=settings.origins)
    app.add_middleware(RequestContext)

    provider = start_tracing(app, engine, span_processor)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(notes_router)
    return app
