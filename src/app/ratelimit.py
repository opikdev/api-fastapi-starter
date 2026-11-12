"""Fixed-window rate limits counted in Postgres, so every instance shares one budget.

Responses describe them with the `RateLimit-Policy` and `RateLimit` fields of
draft-ietf-httpapi-ratelimit-headers.
"""

import ipaddress
import math
from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import case, func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from app.db import RateLimit
from app.problems import ProblemError, Slug

STATE_KEY = "rate_limits"


@dataclass(frozen=True)
class Policy:
    name: str
    quota: int
    window_seconds: int

    def describe(self) -> str:
        return f'"{self.name}";q={self.quota};w={self.window_seconds}'


@dataclass(frozen=True)
class Usage:
    policy: Policy
    count: int
    reset_in: int

    @property
    def exceeded(self) -> bool:
        return self.count > self.policy.quota

    def describe(self) -> str:
        remaining = max(0, self.policy.quota - self.count)
        return f'"{self.policy.name}";r={remaining};t={self.reset_in}'


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


def client_key(connection: HTTPConnection, proxy_hops: int) -> str:
    """The client's IP as a rate-limit key. IPv6 clients share their /64, which one host controls."""
    ip = client_ip(connection, proxy_hops)
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if isinstance(address, ipaddress.IPv4Address):
        return str(address)
    if address.ipv4_mapped is not None:
        return str(address.ipv4_mapped)
    return str(ipaddress.IPv6Network((address, 64), strict=False))


def usages(scope: MutableMapping[str, Any]) -> list[Usage]:
    """The limits counted for this request so far, kept in the ASGI scope for the response."""
    state: dict[str, Any] = scope.setdefault("state", {})
    found: list[Usage] = state.setdefault(STATE_KEY, [])
    return found


def response_headers(counted: list[Usage]) -> dict[str, str]:
    """`RateLimit-Policy` lists every counted policy. On a 429, `RateLimit` shows only the one hit."""
    if not counted:
        return {}
    exceeded = [usage for usage in counted if usage.exceeded]
    return {
        "RateLimit-Policy": ", ".join(usage.policy.describe() for usage in counted),
        "RateLimit": ", ".join(usage.describe() for usage in exceeded[:1] or counted),
    }


async def hit(session: AsyncSession, key: str, policy: Policy) -> Usage:
    """Counts one request against `policy` in its current window, and commits."""
    window = func.now() + func.make_interval(0, 0, 0, 0, 0, 0, policy.window_seconds)
    expired = RateLimit.reset_at <= func.now()
    statement = (
        insert(RateLimit)
        .values(key=key, reset_at=window)
        .on_conflict_do_update(
            index_elements=[RateLimit.key],
            set_={
                "count": case((expired, 1), else_=RateLimit.count + 1),
                "reset_at": case((expired, window), else_=RateLimit.reset_at),
                "updated_at": func.now(),
            },
        )
        # Measured on the database's clock, so skew with this host can't stretch the window.
        .returning(RateLimit.count, func.extract("epoch", RateLimit.reset_at - func.now()))
    )
    count, seconds_left = (await session.execute(statement)).one()
    await session.commit()
    return Usage(policy, count, max(1, math.ceil(seconds_left)))


async def refund(session: AsyncSession, key: str) -> None:
    """Takes back one counted request, such as a login attempt that turned out to succeed."""
    await session.execute(
        update(RateLimit)
        .where(RateLimit.key == key, RateLimit.reset_at > func.now())
        .values(count=func.greatest(RateLimit.count - 1, 0), updated_at=func.now())
    )
    await session.commit()


def rate_limited(usage: Usage, detail: str) -> ProblemError:
    return ProblemError(
        Slug.RATE_LIMITED,
        f"{detail} Retry in {usage.reset_in} seconds.",
        headers={"Retry-After": str(usage.reset_in)},
    )


async def enforce(
    session: AsyncSession, scope: MutableMapping[str, Any], key: str, policy: Policy
) -> None:
    """Counts a request, records it for the response headers, and raises a 429 over the quota."""
    usage = await hit(session, key, policy)
    usages(scope).append(usage)
    if usage.exceeded:
        raise rate_limited(
            usage, f"You've reached the limit of {policy.quota} requests per minute."
        )
