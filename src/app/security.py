"""Password hashing and opaque session tokens."""

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

# OWASP's minimum for argon2id: 19 MiB of memory, 2 iterations, 1 lane.
_hasher = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1)

# A real hash to verify against when the email is unknown, so both answers take the same time.
DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored: str) -> bool:
    try:
        return _hasher.verify(stored, password)
    except VerificationError, InvalidHashError:
        return False


def new_token() -> tuple[str, str]:
    """Returns a random bearer token and the hash to store. Only the hash reaches the database."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
