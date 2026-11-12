"""Keeps procrastinate's tables in step with the installed procrastinate."""

import hashlib
from importlib.metadata import version
from pathlib import Path

VERSIONS = Path(__file__).parents[2] / "src" / "app" / "migrations" / "versions"

# The procrastinate version the migrations bring its schema to. Bump it in the same change as the
# revision that applies procrastinate's upgrade scripts.
MIGRATED_TO = "3.11.0"


def test_migration_0001_creates_procrastinate_3_10_0s_schema_byte_for_byte() -> None:
    frozen = (VERSIONS / "0001_procrastinate_3.10.0.sql").read_bytes()
    assert hashlib.sha256(frozen).hexdigest() == (
        "c70ec4b400a60ad9592787653aae5ae77ae41bf801d56b5bd2712751a07f2009"
    ), "0001_procrastinate_3.10.0.sql is a committed migration. Never edit it"


def test_migrations_bring_procrastinate_to_the_installed_version() -> None:
    installed = version("procrastinate")
    assert installed == MIGRATED_TO, (
        f"procrastinate is {installed}, but the migrations create its schema at {MIGRATED_TO}. "
        "Add an Alembic revision that runs procrastinate's upgrade scripts for every version "
        f"after {MIGRATED_TO} up to {installed}, in order. They are in the folder that "
        "`uv run procrastinate schema --migrations-path` prints. Then set MIGRATED_TO in "
        f"{Path(__file__).name} to {installed}. Never edit 0001_init.py or its SQL file."
    )


def test_revisions_are_numbered_in_order_and_named_after_their_id() -> None:
    revisions = sorted(VERSIONS.glob("[0-9][0-9][0-9][0-9]_*.py"))
    assert revisions
    for number, path in enumerate(revisions, start=1):
        source = path.read_text()
        assert path.name.startswith(f"{number:04d}_"), (
            f"{path.name} breaks the sequence. Create revisions with `make migration name=...`"
        )
        assert f'revision: str = "{number:04d}"' in source, path.name
        previous = f'"{number - 1:04d}"' if number > 1 else "None"
        assert f"down_revision: str | None = {previous}" in source, path.name
