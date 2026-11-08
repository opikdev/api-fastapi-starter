"""Create the app tables and the procrastinate job queue.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from procrastinate.schema import SchemaManager
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rate_limits",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("reset_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rate_limits")),
        sa.UniqueConstraint("key", name=op.f("uq_rate_limits_key")),
    )
    op.create_index(op.f("idx_rate_limits_reset_at"), "rate_limits", ["reset_at"], unique=False)
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("email = lower(email)", name=op.f("chk_users_email_lowercase")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_idempotency_keys_user_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_keys")),
        sa.UniqueConstraint("user_id", "key", name=op.f("uq_idempotency_keys_user_id_key")),
    )
    op.create_index(
        op.f("idx_idempotency_keys_expires_at"), "idempotency_keys", ["expires_at"], unique=False
    )
    op.create_table(
        "notes",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), server_default="", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("char_length(body) <= 10000", name=op.f("chk_notes_body_length")),
        sa.CheckConstraint(
            "char_length(title) between 1 and 200", name=op.f("chk_notes_title_length")
        ),
        sa.CheckConstraint("version > 0", name=op.f("chk_notes_version_positive")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_notes_user_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notes")),
    )
    op.create_index(
        "idx_notes_user_id_id",
        "notes",
        ["user_id", sa.literal_column("id DESC NULLS LAST")],
        unique=False,
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sessions_user_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    op.create_index(op.f("idx_sessions_expires_at"), "sessions", ["expires_at"], unique=False)
    # Procrastinate's tables, functions, and triggers, at the version this lock file pins.
    op.execute(SchemaManager.get_schema())


def downgrade() -> None:
    op.execute("""
        DO $$
        DECLARE item record;
        BEGIN
          FOR item IN SELECT oid::regprocedure AS name FROM pg_proc
            WHERE proname LIKE 'procrastinate%' AND pronamespace = 'public'::regnamespace LOOP
            EXECUTE 'DROP FUNCTION ' || item.name || ' CASCADE';
          END LOOP;
          FOR item IN SELECT tablename FROM pg_tables
            WHERE tablename LIKE 'procrastinate%' AND schemaname = 'public' LOOP
            EXECUTE 'DROP TABLE ' || quote_ident(item.tablename) || ' CASCADE';
          END LOOP;
          FOR item IN SELECT typname FROM pg_type
            WHERE typname LIKE 'procrastinate%' AND typtype IN ('e', 'c')
              AND typnamespace = 'public'::regnamespace LOOP
            EXECUTE 'DROP TYPE IF EXISTS ' || quote_ident(item.typname) || ' CASCADE';
          END LOOP;
        END
        $$;
    """)
    op.drop_index(op.f("idx_sessions_expires_at"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("idx_notes_user_id_id", table_name="notes")
    op.drop_table("notes")
    op.drop_index(op.f("idx_idempotency_keys_expires_at"), table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
    op.drop_table("users")
    op.drop_index(op.f("idx_rate_limits_reset_at"), table_name="rate_limits")
    op.drop_table("rate_limits")
