"""Index sessions by user, for the cascade that deletes a user's sessions with the user.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # IF NOT EXISTS skips an index already built with CONCURRENTLY, as docs/operations.md explains.
    op.create_index(
        op.f("idx_sessions_user_id"), "sessions", ["user_id"], unique=False, if_not_exists=True
    )


def downgrade() -> None:
    op.drop_index(op.f("idx_sessions_user_id"), table_name="sessions")
