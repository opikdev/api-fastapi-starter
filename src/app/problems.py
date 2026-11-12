"""RFC 9457 Problem Details. Every error the API returns goes through `ProblemError`."""

from dataclasses import dataclass, field
from enum import StrEnum

from fastapi.responses import JSONResponse
from pydantic import BaseModel


class Slug(StrEnum):
    VALIDATION_FAILED = "validation-failed"
    INVALID_CREDENTIALS = "invalid-credentials"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not-found"
    METHOD_NOT_ALLOWED = "method-not-allowed"
    EMAIL_TAKEN = "email-taken"
    CONFLICT = "conflict"
    VERSION_MISMATCH = "version-mismatch"
    PAYLOAD_TOO_LARGE = "payload-too-large"
    UNSUPPORTED_MEDIA_TYPE = "unsupported-media-type"
    IDEMPOTENCY_KEY_REUSED = "idempotency-key-reused"
    PRECONDITION_REQUIRED = "precondition-required"
    RATE_LIMITED = "rate-limited"
    INTERNAL_ERROR = "internal-error"
    SERVICE_UNAVAILABLE = "service-unavailable"


CATALOG: dict[Slug, tuple[int, str]] = {
    Slug.VALIDATION_FAILED: (400, "Request validation failed"),
    Slug.INVALID_CREDENTIALS: (401, "Invalid credentials"),
    Slug.UNAUTHORIZED: (401, "Authentication required"),
    Slug.FORBIDDEN: (403, "Forbidden"),
    Slug.NOT_FOUND: (404, "Resource not found"),
    Slug.METHOD_NOT_ALLOWED: (405, "Method not allowed"),
    Slug.EMAIL_TAKEN: (409, "Email already registered"),
    Slug.CONFLICT: (409, "Conflict"),
    Slug.VERSION_MISMATCH: (412, "Resource version mismatch"),
    Slug.PAYLOAD_TOO_LARGE: (413, "Payload too large"),
    Slug.UNSUPPORTED_MEDIA_TYPE: (415, "Unsupported media type"),
    Slug.IDEMPOTENCY_KEY_REUSED: (422, "Idempotency key reused"),
    Slug.PRECONDITION_REQUIRED: (428, "Precondition required"),
    Slug.RATE_LIMITED: (429, "Too many requests"),
    Slug.INTERNAL_ERROR: (500, "Internal server error"),
    Slug.SERVICE_UNAVAILABLE: (503, "Service unavailable"),
}

PROBLEM_EXTENSION = "x-problem"

INVALID_FIELDS = (
    "The request has invalid fields. See `errors` for each one, then fix them and retry."
)


class FieldError(BaseModel):
    field: str
    detail: str


class ProblemBody(BaseModel):
    """The JSON body of every error response."""

    type: str
    title: str
    status: int
    detail: str
    instance: str
    errors: list[FieldError] | None = None


@dataclass
class ProblemError(Exception):
    slug: Slug
    detail: str
    errors: list[FieldError] | None = None
    headers: dict[str, str] = field(default_factory=dict)

    def response(self, instance: str) -> JSONResponse:
        status, title = CATALOG[self.slug]
        body = ProblemBody(
            type=f"urn:problem:{self.slug}",
            title=title,
            status=status,
            detail=self.detail,
            instance=instance,
            errors=self.errors,
        )
        return JSONResponse(
            body.model_dump(exclude_none=True),
            status_code=status,
            headers=self.headers,
            media_type="application/problem+json",
        )


def invalid(field_name: str, detail: str) -> ProblemError:
    return ProblemError(
        Slug.VALIDATION_FAILED, INVALID_FIELDS, [FieldError(field=field_name, detail=detail)]
    )


def responses(*slugs: Slug) -> dict[int | str, dict[str, object]]:
    """Documents a route's own problem responses. `app.openapi` adds the ones middleware returns."""
    return {
        CATALOG[slug][0]: {
            "model": ProblemBody,
            "description": CATALOG[slug][1],
            "content": {"application/problem+json": {}},
            PROBLEM_EXTENSION: slug.value,
        }
        for slug in slugs
    }
