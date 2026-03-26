# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Create personal_access_tokens table.

Revision ID: 009
Revises: 008
"""

from alembic import op
import sqlalchemy as sa

revision: str = "009"
down_revision: str | None = "008"
branch_labels: tuple | None = None
depends_on: tuple | None = None


def upgrade() -> None:
    op.create_table(
        "personal_access_tokens",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("key_prefix", sa.String(8), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_pat_user_id", "personal_access_tokens", ["user_id"])
    # Partial index: only active (non-revoked) tokens for fast prefix lookup.
    # SQLite does not support partial indexes, so this is Postgres-only.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pat_prefix_active "
        "ON personal_access_tokens (key_prefix) "
        "WHERE revoked_at IS NULL"
    )


def downgrade() -> None:
    op.drop_table("personal_access_tokens")
