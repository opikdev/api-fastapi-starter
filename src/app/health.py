"""Liveness and readiness. Liveness stays up during a database outage, so restarts don't pile on."""

from typing import Literal

from fastapi import APIRouter
from sqlalchemy import text

from app.db import DbSession
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
    summary="Check that Postgres is reachable",
    responses=responses(Slug.SERVICE_UNAVAILABLE),
)
async def readiness(session: DbSession) -> Health:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as error:
        raise ProblemError(
            Slug.SERVICE_UNAVAILABLE,
            "Postgres is unreachable. Retry shortly.",
            headers={"Retry-After": "5"},
        ) from error
    return Health()
