# 009. Turn API docs off by default and serve them from the API's origin

- **Status**: accepted
- **Context**: `/docs` and `/openapi.json` map every route for an attacker, and FastAPI's default page loads Swagger UI from a CDN with an inline script, so it can't run under a strict Content Security Policy.
- **Decision**: Serve them only when `DOCS_ENABLED` is `true`, which defaults to `false`. Serve Swagger UI from the pinned `fastapi-swagger` package and a static init script, under a CSP that allows only `'self'`.
- **Consequences**:
  - A production deploy exposes no docs unless someone turns them on. `.env.example`, Compose, and the tests turn them on, so local work is unchanged.
  - The docs page loads nothing from third parties, and Renovate updates Swagger UI like any other dependency.
  - Clients that fetch `/openapi.json` from a running API need `DOCS_ENABLED=true`, or use the committed `openapi.json` instead.
