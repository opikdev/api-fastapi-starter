from http import HTTPStatus
from typing import Any

import httpx2

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.create_note import CreateNote
from ...models.note_out import NoteOut
from ...models.problem_body import ProblemBody
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    body: CreateNote,
    idempotency_key: None | str | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(idempotency_key, Unset):
        headers["idempotency-key"] = idempotency_key

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/notes",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx2.Response
) -> NoteOut | ProblemBody | None:
    if response.status_code == 201:
        response_201 = NoteOut.from_dict(response.json())

        return response_201

    if response.status_code == 400:
        response_400 = ProblemBody.from_dict(response.json())

        return response_400

    if response.status_code == 401:
        response_401 = ProblemBody.from_dict(response.json())

        return response_401

    if response.status_code == 403:
        response_403 = ProblemBody.from_dict(response.json())

        return response_403

    if response.status_code == 413:
        response_413 = ProblemBody.from_dict(response.json())

        return response_413

    if response.status_code == 415:
        response_415 = ProblemBody.from_dict(response.json())

        return response_415

    if response.status_code == 422:
        response_422 = ProblemBody.from_dict(response.json())

        return response_422

    if response.status_code == 429:
        response_429 = ProblemBody.from_dict(response.json())

        return response_429

    if response.status_code == 500:
        response_500 = ProblemBody.from_dict(response.json())

        return response_500

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx2.Response
) -> Response[NoteOut | ProblemBody]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: CreateNote,
    idempotency_key: None | str | Unset = UNSET,
) -> Response[NoteOut | ProblemBody]:
    """Create a note

    Args:
        idempotency_key (None | str | Unset): Replays the original response when a request is
            retried.
        body (CreateNote):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx2.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[NoteOut | ProblemBody]
    """

    kwargs = _get_kwargs(
        body=body,
        idempotency_key=idempotency_key,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    body: CreateNote,
    idempotency_key: None | str | Unset = UNSET,
) -> NoteOut | ProblemBody | None:
    """Create a note

    Args:
        idempotency_key (None | str | Unset): Replays the original response when a request is
            retried.
        body (CreateNote):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx2.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        NoteOut | ProblemBody
    """

    return sync_detailed(
        client=client,
        body=body,
        idempotency_key=idempotency_key,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: CreateNote,
    idempotency_key: None | str | Unset = UNSET,
) -> Response[NoteOut | ProblemBody]:
    """Create a note

    Args:
        idempotency_key (None | str | Unset): Replays the original response when a request is
            retried.
        body (CreateNote):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx2.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[NoteOut | ProblemBody]
    """

    kwargs = _get_kwargs(
        body=body,
        idempotency_key=idempotency_key,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: CreateNote,
    idempotency_key: None | str | Unset = UNSET,
) -> NoteOut | ProblemBody | None:
    """Create a note

    Args:
        idempotency_key (None | str | Unset): Replays the original response when a request is
            retried.
        body (CreateNote):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx2.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        NoteOut | ProblemBody
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
            idempotency_key=idempotency_key,
        )
    ).parsed
