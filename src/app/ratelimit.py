"""Fixed one-minute windows counted in Postgres, so every instance shares one budget."""

import math
from datetime import UTC, datetime

from sqlalchemy import case, func, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from app.db import RateLimit
from app.problems import ProblemError, Slug

WINDOW = text("now() + interval '1 minute'")


def client_ip(connection: HTTPConnection, trust_proxy: bool) -> str:
    if trust_proxy:
        last = connection.headers.get("x-forwarded-for", "").split(",")[-1].strip()
        if last:
            return last
    return connection.client.host if connection.client else "unknown"


async def hit(session: AsyncSession, key: str, limit: int) -> dict[str, str]:
    """Counts one request. Returns the RateLimit headers, or raises a 429 problem over the limit."""
    expired = RateLimit.reset_at <= func.now()
    statement = (
        insert(RateLimit)
        .values(key=key, reset_at=WINDOW)
        .on_conflict_do_update(
            index_elements=[RateLimit.key],
            set_={
                "count": case((expired, 1), else_=RateLimit.count + 1),
                "reset_at": case((expired, WINDOW), else_=RateLimit.reset_at),
                "updated_at": func.now(),
            },
        )
        .returning(RateLimit.count, RateLimit.reset_at)
    )
    count, reset_at = (await session.execute(statement)).one()
    await session.commit()

    reset_in = max(1, math.ceil((reset_at - datetime.now(UTC)).total_seconds()))
    headers = {
        "RateLimit-Limit": str(limit),
        "RateLimit-Remaining": str(max(0, limit - count)),
        "RateLimit-Reset": str(reset_in),
    }
    if count > limit:
        raise ProblemError(
            Slug.RATE_LIMITED,
            f"You've reached the limit of {limit} requests per minute. Retry in {reset_in} seconds.",
            headers=headers | {"Retry-After": str(reset_in)},
        )
    return headers
