"""Upgrade procrastinate's schema from 3.10.0 to 3.11.0.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copies of procrastinate's SQL, so this revision never changes when procrastinate does.
UPGRADE = Path(__file__).with_name("0004_procrastinate_3.11.0.sql")
DOWNGRADE = Path(__file__).with_name("0004_procrastinate_3.10.0_fetch_job.sql")


def upgrade() -> None:
    op.execute(UPGRADE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute(DOWNGRADE.read_text(encoding="utf-8"))
