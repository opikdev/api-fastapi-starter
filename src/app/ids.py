"""Public IDs such as `note_0190a7e4...`: a type prefix and the row's UUIDv7, without dashes."""

import re
from enum import StrEnum
from uuid import UUID

_HEX = re.compile(r"[0-9a-f]{32}")


class Prefix(StrEnum):
    USER = "usr"
    NOTE = "note"


def format_id(prefix: Prefix, value: UUID) -> str:
    return f"{prefix}_{value.hex}"


def parse_id(prefix: Prefix, value: str) -> UUID | None:
    """Returns the UUID behind a public ID, or None when it isn't a valid ID of that kind."""
    head, _, tail = value.partition("_")
    if head != prefix or not _HEX.fullmatch(tail):
        return None
    return UUID(hex=tail)
