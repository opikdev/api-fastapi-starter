# Error reference

Every error is `application/problem+json` per [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457). Switch on `type`, because the other fields can change.

```json
{
  "type": "urn:problem:validation-failed",
  "title": "Request validation failed",
  "status": 400,
  "detail": "The request has invalid fields. See `errors` for each one, then fix them and retry.",
  "instance": "/v1/users",
  "errors": [
    { "field": "password", "detail": "String should have at least 12 characters" }
  ]
}
```

| Type | Status | Meaning |
|---|---|---|
| `urn:problem:validation-failed` | 400 | A field is invalid, the JSON is malformed, `limit` is over 100, or the database rejected a value. An `errors` entry with `field: ""` is about the whole body |
| `urn:problem:invalid-credentials` | 401 | Wrong email or password |
| `urn:problem:unauthorized` | 401 | The token or session cookie is missing, invalid, expired, or revoked |
| `urn:problem:forbidden` | 403 | A browser sent a request that changes data from another origin that isn't in `CORS_ORIGINS` |
| `urn:problem:not-found` | 404 | The route or resource doesn't exist, or isn't yours |
| `urn:problem:method-not-allowed` | 405 | The route exists, but not with this method |
| `urn:problem:email-taken` | 409 | The email is already registered |
| `urn:problem:conflict` | 409 | The request conflicts with existing data, or refers to data that doesn't exist |
| `urn:problem:version-mismatch` | 412 | `If-Match` doesn't match the note's current version, or lists only weak ETags, which never match |
| `urn:problem:payload-too-large` | 413 | The body is over 100 KiB |
| `urn:problem:unsupported-media-type` | 415 | The body isn't sent as `application/json` |
| `urn:problem:idempotency-key-reused` | 422 | The `Idempotency-Key` was used with a different body |
| `urn:problem:precondition-required` | 428 | `If-Match` is missing |
| `urn:problem:rate-limited` | 429 | Too many requests, or too many failed logins for one email. Wait for `Retry-After` seconds |
| `urn:problem:internal-error` | 500 | Unexpected failure. Quote the request ID in `detail` |
| `urn:problem:service-unavailable` | 503 | Postgres is unreachable, or the API is shutting down |

A constraint violation that a route doesn't handle becomes a problem that never names the constraint or the SQL: a unique or foreign key violation is `conflict`, and a check violation is `validation-failed`. Other database errors are `internal-error`.

To add a type, add its slug, status, and title to `src/app/problems.py`, list it in the route's `responses=`, and add a row here. `src/app/openapi.py` documents the problems that middleware returns, such as 403, 413, 415, 429, and 500, on every operation they apply to.
