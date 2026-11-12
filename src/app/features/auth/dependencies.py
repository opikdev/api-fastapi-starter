"""The current user, the session cookie, and the stricter rate limit on registration and login."""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request, Response
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select

from app import ratelimit
from app.db import Session, User
from app.dependencies import DbSession
from app.problems import ProblemError, Slug
from app.security import hash_token

SESSION_COOKIE = "__Host-session"

bearer = HTTPBearer(
    auto_error=False,
    scheme_name="bearerAuth",
    description="A session token from POST /v1/sessions.",
)
cookie = APIKeyCookie(
    name=SESSION_COOKIE,
    auto_error=False,
    scheme_name="cookieAuth",
    description="The cookie POST /v1/sessions sets when `delivery` is `cookie`.",
)


@dataclass(frozen=True)
class CurrentUser:
    session_id: UUID
    id: UUID
    email: str
    created_at: datetime


def set_session_cookie(response: Response, token: str, max_age: int) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="strict")


def _unauthorized(clear_cookie: bool = False) -> ProblemError:
    headers = {"WWW-Authenticate": "Bearer"}
    if clear_cookie:
        cleared = Response()
        clear_session_cookie(cleared)
        headers["Set-Cookie"] = cleared.headers["set-cookie"]
    return ProblemError(
        Slug.UNAUTHORIZED,
        "Send a valid session token in the Authorization header as `Bearer <token>`, "
        'or log in with `delivery: "cookie"` from the same origin.',
        headers=headers,
    )


async def current_user(
    request: Request,
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session_cookie: Annotated[str | None, Depends(cookie)],
) -> CurrentUser:
    from_cookie = "authorization" not in request.headers
    token = session_cookie if from_cookie else credentials and credentials.credentials
    if not token:
        raise _unauthorized()
    row = (
        await session.execute(
            select(Session.id, User.id, User.email, User.created_at)
            .join(User, User.id == Session.user_id)
            .where(Session.token_hash == hash_token(token))
            .where(Session.expires_at > func.now())
        )
    ).one_or_none()
    if row is None:
        raise _unauthorized(clear_cookie=from_cookie)
    return CurrentUser(session_id=row[0], id=row[1], email=row[2], created_at=row[3])


Authenticated = Annotated[CurrentUser, Depends(current_user)]


async def auth_rate_limit(request: Request, session: DbSession) -> None:
    settings = request.app.state.settings
    client = ratelimit.client_key(request, settings.trust_proxy_hops)
    policy = ratelimit.Policy("auth", settings.auth_rate_limit_per_minute, 60)
    await ratelimit.enforce(session, request.scope, f"auth:{client}", policy)
