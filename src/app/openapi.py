"""The OpenAPI document: FastAPI's, plus the problems and headers that middleware adds.

Every /v1 problem response points at a shared component in `components.responses`. Routes list
their own problems with `responses(...)`, and `RULES` adds the ones middleware can return.
"""

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.problems import CATALOG, PROBLEM_EXTENSION, Slug

UNSAFE_METHODS = {"post", "put", "patch", "delete"}
HEADERS: dict[str, dict[str, Any]] = {
    "XRequestId": {
        "description": "The request's ID. Quote it when you report a problem.",
        "schema": {"type": "string"},
    },
    "CacheControl": {
        "description": "Always `no-store` on /v1, so no cache keeps a response.",
        "schema": {"type": "string", "const": "no-store"},
    },
    "RateLimitPolicy": {
        "description": (
            'The rate limits counted for this request, such as `"global";q=300;w=60`: the quota '
            "`q` per window `w` in seconds. See draft-ietf-httpapi-ratelimit-headers."
        ),
        "schema": {"type": "string"},
    },
    "RateLimit": {
        "description": (
            'What is left of each limit, such as `"global";r=238;t=25`: `r` requests remain, '
            "and the window resets in `t` seconds. On a 429, only the limit that was exceeded."
        ),
        "schema": {"type": "string"},
    },
    "RetryAfter": {
        "description": "Seconds to wait before retrying.",
        "schema": {"type": "integer"},
    },
    "ETag": {
        "description": 'The note\'s version, such as `"3"`. Send it back in `If-Match`.',
        "schema": {"type": "string"},
    },
    "Location": {"description": "The path of the created resource.", "schema": {"type": "string"}},
    "IdempotencyReplayed": {
        "description": "`true` when the response replays an earlier request with this key.",
        "schema": {"type": "string", "const": "true"},
    },
    "SetCookie": {
        "description": (
            "Sent when `delivery` is `cookie`: `__Host-session=<token>; Path=/; "
            "Max-Age=<seconds>; HttpOnly; Secure; SameSite=Strict`."
        ),
        "schema": {"type": "string"},
    },
}


def header(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/headers/{name}"}


def _component_name(slug: Slug) -> str:
    return "".join(part.title() for part in slug.value.split("-"))


def _middleware_problems(path: str, method: str, operation: dict[str, Any]) -> set[Slug]:
    """The problems middleware and dependencies can return for an operation, beyond its own."""
    slugs = {Slug.INTERNAL_ERROR}
    if not path.startswith("/v1/"):
        return slugs
    slugs.add(Slug.RATE_LIMITED)
    if method in UNSAFE_METHODS:
        slugs.add(Slug.FORBIDDEN)
    if "requestBody" in operation:
        slugs |= {Slug.VALIDATION_FAILED, Slug.PAYLOAD_TOO_LARGE, Slug.UNSUPPORTED_MEDIA_TYPE}
    if any(parameter["in"] in {"query", "header"} for parameter in operation.get("parameters", [])):
        slugs.add(Slug.VALIDATION_FAILED)
    return slugs


def _problem_response(slug: Slug, v1: bool) -> dict[str, Any]:
    headers = {"X-Request-Id": header("XRequestId")}
    if v1:
        headers |= {
            "Cache-Control": header("CacheControl"),
            "RateLimit": header("RateLimit"),
            "RateLimit-Policy": header("RateLimitPolicy"),
        }
    if slug in {Slug.RATE_LIMITED, Slug.SERVICE_UNAVAILABLE}:
        headers["Retry-After"] = header("RetryAfter")
    return {
        "description": CATALOG[slug][1],
        "headers": headers,
        "content": {
            "application/problem+json": {"schema": {"$ref": "#/components/schemas/ProblemBody"}}
        },
    }


def _document_operation(path: str, method: str, operation: dict[str, Any], used: set[Slug]) -> None:
    v1 = path.startswith("/v1/")
    responses: dict[str, Any] = operation["responses"]
    default_422 = responses.get("422", {}).get("content", {}).get("application/json", {})
    if default_422.get("schema", {}).get("$ref", "").endswith("/HTTPValidationError"):
        del responses["422"]

    slugs = {
        Slug(response.pop(PROBLEM_EXTENSION))
        for response in responses.values()
        if PROBLEM_EXTENSION in response
    }
    slugs |= _middleware_problems(path, method, operation)
    if v1 and operation.get("security") and "401" not in responses:
        slugs.add(Slug.UNAUTHORIZED)
    for slug in sorted(slugs, key=lambda item: CATALOG[item][0]):
        status = str(CATALOG[slug][0])
        if v1:
            responses[status] = {"$ref": f"#/components/responses/{_component_name(slug)}"}
            used.add(slug)
        else:
            responses[status] = _problem_response(slug, v1=False)

    for status, response in responses.items():
        if "$ref" in response or int(status) >= 400:
            continue
        headers = response.setdefault("headers", {})
        headers["X-Request-Id"] = header("XRequestId")
        if v1:
            headers |= {
                "Cache-Control": header("CacheControl"),
                "RateLimit": header("RateLimit"),
                "RateLimit-Policy": header("RateLimitPolicy"),
            }
    operation["responses"] = dict(sorted(responses.items()))


def build(app: FastAPI) -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    used: set[Slug] = set()
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            _document_operation(path, method, operation, used)
    components = schema.setdefault("components", {})
    for name in ("HTTPValidationError", "ValidationError"):
        components.get("schemas", {}).pop(name, None)
    components["responses"] = {
        _component_name(slug): _problem_response(slug, v1=True)
        for slug in sorted(used, key=lambda item: (CATALOG[item][0], item.value))
    }
    components["headers"] = HEADERS
    app.openapi_schema = schema
    return schema
