"""POST /v1/users, POST /v1/sessions, DELETE /v1/sessions/current, and GET /v1/users/me."""

from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from pydantic import EmailStr, Field
from pydantic.json_schema import SkipJsonSchema
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from app import jobs
from app.db import Session, User
from app.dependencies import DbSession
from app.features.auth.dependencies import (
    Authenticated,
    auth_rate_limit,
    clear_session_cookie,
    set_session_cookie,
)
from app.ids import Prefix, format_id
from app.problems import ProblemError, Slug, responses
from app.schema import ApiModel
from app.security import DUMMY_HASH, hash_password, new_token, verify_password

router = APIRouter(prefix="/v1", tags=["auth"])


class Credentials(ApiModel):
    email: Annotated[EmailStr, Field(max_length=254, examples=["demo@example.com"])]
    password: Annotated[
        str, Field(min_length=12, max_length=128, examples=["correct-horse-battery"])
    ]


class CreateSession(Credentials):
    delivery: Annotated[
        Literal["body", "cookie"],
        Field(
            description=(
                "`body` returns the token. `cookie` sets it in an httpOnly `__Host-session` "
                "cookie instead, for a browser app on the same origin as the API."
            ),
            examples=["cookie"],
        ),
    ] = "body"


class UserOut(ApiModel):
    id: str = Field(examples=["usr_0190a7e4c1d27c3e9b8f6a5d4c3b2a10"])
    email: str
    created_at: datetime


class SessionOut(ApiModel):
    token: Annotated[
        str | SkipJsonSchema[None],
        Field(
            description=(
                "Present when `delivery` is `body`. Send it as `Authorization: Bearer <token>`."
            )
        ),
    ] = None
    expires_at: datetime


def present(user_id: object, email: str, created_at: datetime) -> UserOut:
    return UserOut(id=format_id(Prefix.USER, user_id), email=email, created_at=created_at)  # type: ignore[arg-type]


@router.post(
    "/users",
    status_code=status.HTTP_201_CREATED,
    operation_id="createUser",
    summary="Register a user",
    dependencies=[Depends(auth_rate_limit)],
    responses=responses(Slug.VALIDATION_FAILED, Slug.EMAIL_TAKEN, Slug.RATE_LIMITED),
)
async def create_user(body: Credentials, session: DbSession) -> UserOut:
    email = body.email.lower()
    password_hash = await run_in_threadpool(hash_password, body.password)
    statement = (
        insert(User)
        .values(email=email, password_hash=password_hash)
        .on_conflict_do_nothing(index_elements=[User.email])
        .returning(User.id, User.email, User.created_at)
    )
    row = (await session.execute(statement)).one_or_none()
    if row is None:
        raise ProblemError(Slug.EMAIL_TAKEN, f"{email} is already registered. Log in instead.")
    await jobs.defer(session, jobs.send_welcome_email, user_id=str(row[0]))
    await session.commit()
    return present(row[0], row[1], row[2])


@router.post(
    "/sessions",
    status_code=status.HTTP_201_CREATED,
    operation_id="createSession",
    summary="Log in",
    dependencies=[Depends(auth_rate_limit)],
    response_model_exclude_none=True,
    responses={
        **responses(Slug.VALIDATION_FAILED, Slug.INVALID_CREDENTIALS, Slug.RATE_LIMITED),
        201: {
            "headers": {
                "Set-Cookie": {
                    "description": (
                        "Sent when `delivery` is `cookie`: `__Host-session=<token>; Path=/; "
                        "Max-Age=<seconds>; HttpOnly; Secure; SameSite=Strict`."
                    ),
                    "schema": {"type": "string"},
                }
            }
        },
    },
)
async def create_session(
    body: CreateSession, session: DbSession, request: Request, response: Response
) -> SessionOut:
    user = (
        await session.execute(select(User).where(User.email == body.email.lower()))
    ).scalar_one_or_none()
    # Verify against a dummy hash for unknown emails, so both answers take the same time.
    matches = await run_in_threadpool(
        verify_password, body.password, user.password_hash if user else DUMMY_HASH
    )
    if user is None or not matches:
        raise ProblemError(Slug.INVALID_CREDENTIALS, "The email or password is wrong.")

    token, token_hash = new_token()
    ttl = timedelta(hours=request.app.state.settings.session_ttl_hours)
    expires_at = (
        await session.execute(
            insert(Session)
            .values(user_id=user.id, token_hash=token_hash, expires_at=func.now() + ttl)
            .returning(Session.expires_at)
        )
    ).scalar_one()
    await session.commit()
    response.headers["Cache-Control"] = "no-store"
    if body.delivery == "cookie":
        set_session_cookie(response, token, int(ttl.total_seconds()))
        return SessionOut(expires_at=expires_at)
    return SessionOut(token=token, expires_at=expires_at)


@router.delete(
    "/sessions/current",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteCurrentSession",
    summary="Log out",
    responses=responses(Slug.UNAUTHORIZED),
)
async def delete_current_session(
    user: Authenticated, session: DbSession, response: Response
) -> None:
    await session.execute(delete(Session).where(Session.id == user.session_id))
    await session.commit()
    clear_session_cookie(response)


@router.get(
    "/users/me",
    operation_id="getCurrentUser",
    summary="Get the current user",
    responses=responses(Slug.UNAUTHORIZED),
)
async def get_current_user(user: Authenticated) -> UserOut:
    return present(user.id, user.email, user.created_at)
