"""Liveness and readiness. Liveness stays up during a database outage, so restarts don't pile on."""

from typing import Literal

from fastapi import APIRouter, Request
from opentelemetry.instrumentation.utils import suppress_instrumentation
from sqlalchemy import text

from app.dependencies import DbSession
from app.problems import ProblemError, Slug, responses
from app.schema import ApiModel

router = APIRouter(tags=["health"])


class Health(ApiModel):
    status: Literal["ok"] = "ok"


@router.get("/healthz", operation_id="getLiveness", summary="Check that the process is up")
async def liveness() -> Health:
    return Health()


@router.get(
    "/readyz",
    operation_id="getReadiness",
    summary="Check that the API takes traffic and Postgres is reachable",
    responses=responses(Slug.SERVICE_UNAVAILABLE),
)
async def readiness(request: Request, session: DbSession) -> Health:
    if request.app.state.draining:
        raise ProblemError(
            Slug.SERVICE_UNAVAILABLE,
            "The API is shutting down. Send traffic to another instance.",
        )
    try:
        # Probes run every few seconds, so their query would flood traces.
        with suppress_instrumentation():
            await session.execute(text("SELECT 1"))
    except Exception as error:
        raise ProblemError(
            Slug.SERVICE_UNAVAILABLE,
            "Postgres is unreachable. Retry shortly.",
            headers={"Retry-After": "5"},
        ) from error
    return Health()
