"""The current user, and the stricter rate limit on registration and login."""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select

from app import ratelimit
from app.db import DbSession, Session, User
from app.problems import ProblemError, Slug
from app.security import hash_token

bearer = HTTPBearer(auto_error=False, description="A session token from POST /v1/sessions.")


@dataclass(frozen=True)
class CurrentUser:
    session_id: UUID
    id: UUID
    email: str
    created_at: datetime


def _unauthorized() -> ProblemError:
    return ProblemError(
        Slug.UNAUTHORIZED,
        "Send a valid session token in the Authorization header as `Bearer <token>`.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def current_user(
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    row = (
        await session.execute(
            select(Session.id, User.id, User.email, User.created_at)
            .join(User, User.id == Session.user_id)
            .where(Session.token_hash == hash_token(credentials.credentials))
            .where(Session.expires_at > func.now())
        )
    ).one_or_none()
    if row is None:
        raise _unauthorized()
    return CurrentUser(session_id=row[0], id=row[1], email=row[2], created_at=row[3])


Authenticated = Annotated[CurrentUser, Depends(current_user)]


async def auth_rate_limit(request: Request, response: Response, session: DbSession) -> None:
    settings = request.app.state.settings
    ip = ratelimit.client_ip(request, settings.trust_proxy)
    headers = await ratelimit.hit(session, f"auth:{ip}", settings.auth_rate_limit_per_minute)
    response.headers.update(headers)
