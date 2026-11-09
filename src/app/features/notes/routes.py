"""CRUD for notes, scoped to the caller. Another user's note looks like it doesn't exist."""

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response, status
from pydantic import Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import IdempotencyKey, Note
from app.dependencies import DbSession
from app.features.auth.dependencies import Authenticated
from app.ids import Prefix, format_id, parse_id
from app.problems import ProblemError, Slug, invalid, responses
from app.schema import ApiModel

router = APIRouter(prefix="/v1/notes", tags=["notes"])

DEFAULT_PAGE_SIZE = 20
IF_MATCH = re.compile(r'^"(\d+)"$')
IDEMPOTENCY_TTL = timedelta(hours=24)


class NoteOut(ApiModel):
    id: str = Field(examples=["note_0190a7e4c1d27c3e9b8f6a5d4c3b2a10"])
    title: str
    body: str
    version: int
    created_at: datetime
    updated_at: datetime


class CreateNote(ApiModel):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    body: Annotated[str, Field(max_length=10_000)] = ""


class UpdateNote(ApiModel):
    title: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    body: Annotated[str | None, Field(max_length=10_000)] = None


class PageMeta(ApiModel):
    limit: int
    next_cursor: str | None


class NoteList(ApiModel):
    data: list[NoteOut]
    meta: PageMeta


def present(note: Note) -> NoteOut:
    return NoteOut(
        id=format_id(Prefix.NOTE, note.id),
        title=note.title,
        body=note.body,
        version=note.version,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


def etag(version: int) -> str:
    return f'"{version}"'


def not_found(note_id: str) -> ProblemError:
    return ProblemError(Slug.NOT_FOUND, f"Note {note_id} does not exist.")


def check_text(**fields: str | None) -> None:
    for name, value in fields.items():
        if value is not None and "\x00" in value:
            raise invalid(name, "must not contain NUL characters")


async def find(session: AsyncSession, note_id: UUID, user_id: UUID) -> Note | None:
    statement = select(Note).where(Note.id == note_id, Note.user_id == user_id)
    return (await session.execute(statement)).scalar_one_or_none()


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    operation_id="createNote",
    summary="Create a note",
    responses=responses(
        Slug.VALIDATION_FAILED, Slug.UNAUTHORIZED, Slug.IDEMPOTENCY_KEY_REUSED, Slug.RATE_LIMITED
    ),
)
async def create_note(
    body: CreateNote,
    user: Authenticated,
    session: DbSession,
    request: Request,
    response: Response,
    idempotency_key: Annotated[
        str | None,
        Header(
            min_length=1,
            max_length=255,
            description="Replays the original response when a request is retried.",
        ),
    ] = None,
) -> NoteOut:
    title = body.title.strip()
    check_text(title=title, body=body.body)
    if not title:
        raise invalid("title", "must not be blank")

    endpoint = f"{request.method} {request.scope['route'].path}"
    note, replayed = await create_idempotently(
        session, user.id, endpoint, idempotency_key, title, body.body
    )
    response.headers["ETag"] = etag(note.version)
    response.headers["Location"] = f"/v1/notes/{note.id}"
    if replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return note


async def create_idempotently(
    session: AsyncSession, user_id: UUID, endpoint: str, key: str | None, title: str, body: str
) -> tuple[NoteOut, bool]:
    """Writes the key and the note in one transaction, so a retry replays instead of duplicating.

    Keys are scoped to the user and the endpoint, and an expired key is claimed again as new.
    A concurrent duplicate waits on the key's unique index until the first commits, then replays it.
    """
    claim: UUID | None = None
    if key is not None:
        request_hash = hashlib.sha256(
            json.dumps({"title": title, "body": body}, separators=(",", ":")).encode()
        ).hexdigest()
        statement = insert(IdempotencyKey).values(
            user_id=user_id,
            endpoint=endpoint,
            key=key,
            request_hash=request_hash,
            response_body={},
            expires_at=func.now() + IDEMPOTENCY_TTL,
        )
        claim = (
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[
                        IdempotencyKey.user_id,
                        IdempotencyKey.endpoint,
                        IdempotencyKey.key,
                    ],
                    set_={
                        "request_hash": statement.excluded.request_hash,
                        "response_body": statement.excluded.response_body,
                        "expires_at": statement.excluded.expires_at,
                        "updated_at": func.now(),
                    },
                    where=IdempotencyKey.expires_at <= func.now(),
                ).returning(IdempotencyKey.id)
            )
        ).scalar_one_or_none()
        if claim is None:
            original = (
                await session.execute(
                    select(IdempotencyKey).where(
                        IdempotencyKey.user_id == user_id,
                        IdempotencyKey.endpoint == endpoint,
                        IdempotencyKey.key == key,
                    )
                )
            ).scalar_one()
            if original.request_hash != request_hash:
                raise ProblemError(
                    Slug.IDEMPOTENCY_KEY_REUSED,
                    "This Idempotency-Key was used with a different request body. Use a new key.",
                )
            return NoteOut.model_validate(original.response_body), True

    row = (
        await session.execute(
            insert(Note).values(user_id=user_id, title=title, body=body).returning(Note)
        )
    ).scalar_one()
    note = present(row)
    if claim is not None:
        stored: dict[str, Any] = note.model_dump(mode="json", by_alias=True)
        await session.execute(
            update(IdempotencyKey)
            .where(IdempotencyKey.id == claim)
            .values(response_body=stored, updated_at=func.now())
        )
    await session.commit()
    return note, False


@router.get(
    "",
    operation_id="listNotes",
    summary="List notes, newest first",
    responses=responses(Slug.VALIDATION_FAILED, Slug.UNAUTHORIZED, Slug.RATE_LIMITED),
)
async def list_notes(
    user: Authenticated,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[
        str | None, Query(max_length=100, description="meta.nextCursor from a previous page.")
    ] = None,
) -> NoteList:
    statement = select(Note).where(Note.user_id == user.id)
    if cursor is not None:
        after = parse_id(Prefix.NOTE, cursor)
        if after is None:
            raise invalid(
                "cursor", "isn't a valid cursor. Use meta.nextCursor from a previous response"
            )
        statement = statement.where(Note.id < after)
    rows = (await session.execute(statement.order_by(Note.id.desc()).limit(limit + 1))).scalars()
    data = [present(row) for row in rows]
    next_cursor = data[limit - 1].id if len(data) > limit else None
    return NoteList(data=data[:limit], meta=PageMeta(limit=limit, next_cursor=next_cursor))


@router.get(
    "/{note_id}",
    operation_id="getNote",
    summary="Get a note",
    responses=responses(Slug.UNAUTHORIZED, Slug.NOT_FOUND, Slug.RATE_LIMITED),
)
async def get_note(
    note_id: str, user: Authenticated, session: DbSession, response: Response
) -> NoteOut:
    parsed = parse_id(Prefix.NOTE, note_id)
    row = await find(session, parsed, user.id) if parsed else None
    if row is None:
        raise not_found(note_id)
    response.headers["ETag"] = etag(row.version)
    return present(row)


@router.patch(
    "/{note_id}",
    operation_id="updateNote",
    summary="Update a note",
    responses=responses(
        Slug.VALIDATION_FAILED,
        Slug.UNAUTHORIZED,
        Slug.NOT_FOUND,
        Slug.VERSION_MISMATCH,
        Slug.PRECONDITION_REQUIRED,
        Slug.RATE_LIMITED,
    ),
)
async def update_note(
    note_id: str,
    patch: UpdateNote,
    user: Authenticated,
    session: DbSession,
    response: Response,
    if_match: Annotated[
        str | None, Header(description="The ETag from your last read of this note.")
    ] = None,
) -> NoteOut:
    if if_match is None:
        raise ProblemError(
            Slug.PRECONDITION_REQUIRED,
            "Send the If-Match header with the ETag from your last read of this note.",
        )
    match = IF_MATCH.match(if_match)
    if match is None or int(match[1]) > 2**31 - 1:
        raise ProblemError(Slug.VERSION_MISMATCH, f"If-Match {if_match} is not a current ETag.")
    version = int(match[1])
    parsed = parse_id(Prefix.NOTE, note_id)
    if parsed is None:
        raise not_found(note_id)

    changes = patch.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        raise invalid("body", "needs title, body, or both")
    if "title" in changes:
        changes["title"] = changes["title"].strip()
        if not changes["title"]:
            raise invalid("title", "must not be blank")
    check_text(**changes)

    row = (
        await session.execute(
            update(Note)
            .where(Note.id == parsed, Note.user_id == user.id, Note.version == version)
            .values(**changes, version=Note.version + 1, updated_at=func.now())
            .returning(Note)
        )
    ).scalar_one_or_none()
    if row is None:
        current = await find(session, parsed, user.id)
        if current is None:
            raise not_found(note_id)
        raise ProblemError(
            Slug.VERSION_MISMATCH,
            f"Note {note_id} is at version {current.version}. Fetch it again, then retry.",
        )
    await session.commit()
    response.headers["ETag"] = etag(row.version)
    return present(row)


@router.delete(
    "/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteNote",
    summary="Delete a note",
    responses=responses(Slug.UNAUTHORIZED, Slug.NOT_FOUND, Slug.RATE_LIMITED),
)
async def delete_note(note_id: str, user: Authenticated, session: DbSession) -> None:
    parsed = parse_id(Prefix.NOTE, note_id)
    if parsed is None:
        raise not_found(note_id)
    result = await session.execute(
        delete(Note).where(Note.id == parsed, Note.user_id == user.id).returning(Note.id)
    )
    if result.scalar_one_or_none() is None:
        raise not_found(note_id)
    await session.commit()
