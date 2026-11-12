# 008. Key rate limits by network and limit failed logins per account

- **Status**: accepted
- **Context**: Limits keyed by the exact IP are easy to dodge over IPv6, where one host usually controls a whole /64. Per-IP limits also can't stop a slow password-guessing attack from many addresses against one account. The three API starters must behave the same.
- **Decision**: Key IP limits by the IPv4 address, or the IPv6 /64, with IPv4-mapped IPv6 counted as IPv4. Add a failed-login limit keyed by a SHA-256 hash of the normalized email, whether or not the account exists. Describe every limit with the `RateLimit-Policy` and `RateLimit` fields of draft-ietf-httpapi-ratelimit-headers.
- **Consequences**:
  - One IPv6 host can't rotate addresses to get a fresh budget, but clients behind one /64 or one IPv4 NAT share a budget.
  - Someone who knows an email can lock that account out of password login for `LOGIN_FAILURE_WINDOW_SECONDS`. Sessions that are already open keep working. Lower the window if lockouts hurt more than guessing does.
  - A 429 looks the same for existing and unknown emails, and still costs a password hash, so it reveals nothing.
  - The login attempt is counted before the password check and refunded on success, so parallel guesses can't slip past the limit.
  - The old `RateLimit-Limit`, `RateLimit-Remaining`, and `RateLimit-Reset` headers are gone, which breaks clients that read them.
