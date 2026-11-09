"""Scope idempotency keys to an endpoint, so one key can't replay another endpoint's response.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Every existing key came from POST /v1/notes, the only endpoint that took one.
    op.add_column(
        "idempotency_keys",
        sa.Column("endpoint", sa.Text(), server_default="POST /v1/notes", nullable=False),
    )
    op.alter_column("idempotency_keys", "endpoint", server_default=None)
    op.create_unique_constraint(
        op.f("uq_idempotency_keys_user_id_endpoint_key"),
        "idempotency_keys",
        ["user_id", "endpoint", "key"],
    )
    op.drop_constraint(op.f("uq_idempotency_keys_user_id_key"), "idempotency_keys", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint(
        op.f("uq_idempotency_keys_user_id_key"), "idempotency_keys", ["user_id", "key"]
    )
    op.drop_constraint(
        op.f("uq_idempotency_keys_user_id_endpoint_key"), "idempotency_keys", type_="unique"
    )
    op.drop_column("idempotency_keys", "endpoint")
