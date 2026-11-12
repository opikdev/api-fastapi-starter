from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx2

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.note_out import NoteOut
from ...models.problem_body import ProblemBody
from ...models.update_note import UpdateNote
from ...types import UNSET, Response, Unset


def _get_kwargs(
    note_id: str,
    *,
    body: UpdateNote,
    if_match: None | str | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(if_match, Unset):
        headers["if-match"] = if_match

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/v1/notes/{note_id}".format(
            note_id=quote(str(note_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx2.Response
) -> NoteOut | ProblemBody | None:
    if response.status_code == 200:
        response_200 = NoteOut.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = ProblemBody.from_dict(response.json())

        return response_400

    if response.status_code == 401:
        response_401 = ProblemBody.from_dict(response.json())

        return response_401

    if response.status_code == 403:
        response_403 = ProblemBody.from_dict(response.json())

        return response_403

    if response.status_code == 404:
        response_404 = ProblemBody.from_dict(response.json())

        return response_404

    if response.status_code == 412:
        response_412 = ProblemBody.from_dict(response.json())

        return response_412

    if response.status_code == 413:
        response_413 = ProblemBody.from_dict(response.json())

        return response_413

    if response.status_code == 415:
        response_415 = ProblemBody.from_dict(response.json())

        return response_415

    if response.status_code == 428:
        response_428 = ProblemBody.from_dict(response.json())

        return response_428

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
    note_id: str,
    *,
    client: AuthenticatedClient,
    body: UpdateNote,
    if_match: None | str | Unset = UNSET,
) -> Response[NoteOut | ProblemBody]:
    """Update a note

    Args:
        note_id (str):
        if_match (None | str | Unset): The ETag from your last read of this note, or `*` to update
            whatever the current version is. Weak ETags never match.
        body (UpdateNote):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx2.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[NoteOut | ProblemBody]
    """

    kwargs = _get_kwargs(
        note_id=note_id,
        body=body,
        if_match=if_match,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    note_id: str,
    *,
    client: AuthenticatedClient,
    body: UpdateNote,
    if_match: None | str | Unset = UNSET,
) -> NoteOut | ProblemBody | None:
    """Update a note

    Args:
        note_id (str):
        if_match (None | str | Unset): The ETag from your last read of this note, or `*` to update
            whatever the current version is. Weak ETags never match.
        body (UpdateNote):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx2.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        NoteOut | ProblemBody
    """

    return sync_detailed(
        note_id=note_id,
        client=client,
        body=body,
        if_match=if_match,
    ).parsed


async def asyncio_detailed(
    note_id: str,
    *,
    client: AuthenticatedClient,
    body: UpdateNote,
    if_match: None | str | Unset = UNSET,
) -> Response[NoteOut | ProblemBody]:
    """Update a note

    Args:
        note_id (str):
        if_match (None | str | Unset): The ETag from your last read of this note, or `*` to update
            whatever the current version is. Weak ETags never match.
        body (UpdateNote):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx2.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[NoteOut | ProblemBody]
    """

    kwargs = _get_kwargs(
        note_id=note_id,
        body=body,
        if_match=if_match,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    note_id: str,
    *,
    client: AuthenticatedClient,
    body: UpdateNote,
    if_match: None | str | Unset = UNSET,
) -> NoteOut | ProblemBody | None:
    """Update a note

    Args:
        note_id (str):
        if_match (None | str | Unset): The ETag from your last read of this note, or `*` to update
            whatever the current version is. Weak ETags never match.
        body (UpdateNote):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx2.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        NoteOut | ProblemBody
    """

    return (
        await asyncio_detailed(
            note_id=note_id,
            client=client,
            body=body,
            if_match=if_match,
        )
    ).parsed
