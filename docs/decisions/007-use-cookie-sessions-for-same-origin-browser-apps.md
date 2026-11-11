# 007. Use cookie sessions for same-origin browser apps

- **Status**: accepted
- **Context**: A browser app that stores a bearer token where JavaScript can read it loses the session to any XSS. A cookie fixes that, but browsers send cookies on cross-site requests, so it brings CSRF, and it must match the API in Hono and Go.
- **Decision**: Let `POST /v1/sessions` set the same opaque token in an `HttpOnly`, `Secure`, `SameSite=Strict` cookie named `__Host-session` when asked with `delivery: "cookie"`, and block cross-origin unsafe requests on `/v1` with `Sec-Fetch-Site` and `Origin`, as Go's `CrossOriginProtection` does. Bearer tokens stay the default.
- **Consequences**:
  - Scripts can't read the session. `__Host-` pins the cookie to the API's host and path `/`, and `SameSite=Strict` with the cross-origin check stops CSRF and login CSRF without CSRF tokens.
  - The browser app must share the API's origin, such as through a reverse proxy, because CORS never allows credentials. Other origins use bearer tokens.
  - Bearer stays the default, so CLIs, servers, and mobile apps work as before, and an `Authorization` header always wins over the cookie.
  - Browser requests that change data from an origin not in `CORS_ORIGINS` get 403, whatever the auth.
