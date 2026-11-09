"""Fixed one-minute windows counted in Postgres, so every instance shares one budget."""

import ipaddress
import math
from datetime import UTC, datetime

from sqlalchemy import case, func, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from app.db import RateLimit
from app.problems import ProblemError, Slug

WINDOW = text("now() + interval '1 minute'")


def client_ip(connection: HTTPConnection, proxy_hops: int) -> str:
    """The client's address: the socket's, or the one `proxy_hops` from the right of X-Forwarded-For.

    Each trusted proxy appends the address it saw, so the entry `proxy_hops` from the right is the
    last one a trusted proxy wrote. Entries further left come from the client and can be forged.
    """
    socket = connection.client.host if connection.client else "unknown"
    forwarded = [
        entry.strip()
        for header in connection.headers.getlist("x-forwarded-for")
        for entry in header.split(",")
    ]
    if proxy_hops == 0 or not forwarded:
        return socket
    chosen = forwarded[-proxy_hops] if proxy_hops <= len(forwarded) else forwarded[0]
    try:
        return str(ipaddress.ip_address(chosen))
    except ValueError:
        return socket


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
