# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Rename users.handle to users.username.

Revision ID: 012
Revises: 011
"""

from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("users", "handle", new_column_name="username")
    op.execute("ALTER INDEX idx_users_handle RENAME TO idx_users_username")


def downgrade() -> None:
    op.alter_column("users", "username", new_column_name="handle")
    op.execute("ALTER INDEX idx_users_username RENAME TO idx_users_handle")
