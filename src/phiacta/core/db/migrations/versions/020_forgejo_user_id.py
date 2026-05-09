# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Add forgejo_user_id column to users table for Forgejo user provisioning.

Revision ID: 020
Revises: 019
"""

from alembic import op
import sqlalchemy as sa

revision: str = "020"
down_revision: str | None = "019"
branch_labels: tuple | None = None
depends_on: tuple | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("forgejo_user_id", sa.Integer(), nullable=True))
    op.create_index("ix_users_forgejo_user_id", "users", ["forgejo_user_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_forgejo_user_id", table_name="users")
    op.drop_column("users", "forgejo_user_id")
