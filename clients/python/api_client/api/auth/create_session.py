from http import HTTPStatus
from typing import Any

import httpx2

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.create_session import CreateSession
from ...models.problem_body import ProblemBody
from ...models.session_out import SessionOut
from ...types import Response


def _get_kwargs(
    *,
    body: CreateSession,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/sessions",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx2.Response
) -> ProblemBody | SessionOut | None:
    if response.status_code == 201:
        response_201 = SessionOut.from_dict(response.json())

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
) -> Response[ProblemBody | SessionOut]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: CreateSession,
) -> Response[ProblemBody | SessionOut]:
    """Log in

    Args:
        body (CreateSession):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx2.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemBody | SessionOut]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    body: CreateSession,
) -> ProblemBody | SessionOut | None:
    """Log in

    Args:
        body (CreateSession):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx2.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemBody | SessionOut
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: CreateSession,
) -> Response[ProblemBody | SessionOut]:
    """Log in

    Args:
        body (CreateSession):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx2.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemBody | SessionOut]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    body: CreateSession,
) -> ProblemBody | SessionOut | None:
    """Log in

    Args:
        body (CreateSession):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx2.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemBody | SessionOut
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
