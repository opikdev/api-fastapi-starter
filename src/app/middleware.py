"""ASGI middleware, outermost first: request IDs and logs, headers, CORS, HEAD, and /v1 guards."""

import logging
import secrets
import time
from contextvars import ContextVar

from opentelemetry import trace
from opentelemetry.trace import StatusCode
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import ratelimit
from app.problems import ProblemError, Slug

MAX_BODY_BYTES = 100 * 1024
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Strict-Transport-Security": "max-age=15552000; includeSubDomains",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
}

request_id: ContextVar[str] = ContextVar("request_id", default="")
logger = logging.getLogger("app.http")


async def _send_problem(scope: Scope, send: Send, problem: ProblemError) -> None:
    async def receive() -> Message:  # pragma: no cover - the response never reads the body
        return {"type": "http.request", "body": b""}

    await problem.response(scope["path"])(scope, receive, send)


class RequestContext:
    """Gives each request an ID, adds security headers, and logs it once it completes."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = secrets.token_hex(16)
        token = request_id.set(rid)
        started = time.perf_counter()
        status = 500
        response_started = False

        async def send_with_headers(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status, response_started = message["status"], True
                headers = MutableHeaders(scope=message)
                headers["X-Request-Id"] = rid
                for name, value in SECURITY_HEADERS.items():
                    headers[name] = value
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception as error:
            # The error boundary: log and trace the real error, and show the client only an ID.
            logger.exception("Unhandled error", extra={"requestId": rid})
            span = trace.get_current_span()
            span.record_exception(error)
            span.set_status(StatusCode.ERROR, "unhandled error")
            if not response_started:
                problem = ProblemError(
                    Slug.INTERNAL_ERROR,
                    f"Something went wrong on our side. Retry, and quote request {rid} if it persists.",
                )
                await _send_problem(scope, send_with_headers, problem)
        finally:
            logger.info(
                "Request completed",
                extra={
                    "requestId": rid,
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status,
                    "durationMs": round((time.perf_counter() - started) * 1000),
                },
            )
            request_id.reset(token)


class Cors:
    """Allows only the configured browser origins, and only on /v1."""

    def __init__(self, app: ASGIApp, origins: list[str]) -> None:
        self.app = app
        self.origins = set(origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        origin = Headers(scope=scope).get("origin") if scope["type"] == "http" else None
        if not origin or origin not in self.origins or not scope["path"].startswith("/v1/"):
            await self.app(scope, receive, send)
            return
        if scope["method"] == "OPTIONS":
            await send(
                {
                    "type": "http.response.start",
                    "status": 204,
                    "headers": [
                        (b"access-control-allow-origin", origin.encode()),
                        (b"vary", b"Origin"),
                        (b"access-control-allow-methods", b"GET, POST, PATCH, DELETE"),
                        (
                            b"access-control-allow-headers",
                            b"Authorization, Content-Type, Idempotency-Key, If-Match",
                        ),
                        (b"access-control-expose-headers", b"ETag, Location, Retry-After"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_with_origin(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Access-Control-Allow-Origin"] = origin
                headers.append("Vary", "Origin")
            await send(message)

        await self.app(scope, receive, send_with_origin)


class HeadAsGet:
    """Answers HEAD like GET without a body, so routes only need GET."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "HEAD":
            await self.app(scope, receive, send)
            return

        async def send_headers_only(message: Message) -> None:
            if message["type"] == "http.response.body":
                message = {**message, "body": b""}
            await send(message)

        await self.app({**scope, "method": "GET"}, receive, send_headers_only)


class GuardV1:
    """On /v1: counts the global rate limit, caps the body at 100 KiB, and requires JSON bodies."""

    def __init__(
        self,
        app: ASGIApp,
        sessions: async_sessionmaker[AsyncSession],
        limit: int,
        trust_proxy: bool,
    ) -> None:
        self.app = app
        self.sessions = sessions
        self.limit = limit
        self.trust_proxy = trust_proxy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/v1/"):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        try:
            async with self.sessions() as session:
                ip = ratelimit.client_ip(HTTPConnection(scope), self.trust_proxy)
                limit_headers = await ratelimit.hit(session, f"global:{ip}", self.limit)
            self._check_body(scope, headers)
        except ProblemError as problem:
            await _send_problem(scope, send, problem)
            return

        # Read the body up front, so a chunked body over the limit gets a 413 before the app runs.
        body, more = b"", True
        while more:
            message = await receive()
            if message["type"] != "http.request":
                break
            body += message.get("body", b"")
            more = message.get("more_body", False)
            if len(body) > MAX_BODY_BYTES:
                await _send_problem(scope, send, ProblemError(Slug.PAYLOAD_TOO_LARGE, _too_large()))
                return
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        async def send_with_limits(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                for name, value in limit_headers.items():
                    response_headers.setdefault(name, value)
            await send(message)

        await self.app(scope, replay, send_with_limits)

    @staticmethod
    def _check_body(scope: Scope, headers: Headers) -> None:
        length = headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
            raise ProblemError(Slug.PAYLOAD_TOO_LARGE, _too_large())
        has_body = (length and length != "0") or "transfer-encoding" in headers
        content_type = headers.get("content-type", "").split(";")[0].strip().lower()
        if (
            scope["method"] in {"POST", "PATCH", "PUT"}
            and has_body
            and content_type != "application/json"
        ):
            raise ProblemError(
                Slug.UNSUPPORTED_MEDIA_TYPE,
                "Send the body as JSON, with the header Content-Type: application/json.",
            )


def _too_large() -> str:
    return f"The request body is over the {MAX_BODY_BYTES}-byte limit."
