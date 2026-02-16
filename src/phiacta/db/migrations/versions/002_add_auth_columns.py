# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Add auth columns to agents: email, password_hash, is_active.

Revision ID: 002
Revises: 001
Create Date: 2026-02-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: str = "001"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("email", sa.Text(), nullable=True))
    op.add_column("agents", sa.Column("password_hash", sa.Text(), nullable=True))
    op.add_column(
        "agents",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index(
        "idx_agents_email_unique",
        "agents",
        ["email"],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_agents_email_unique", table_name="agents")
    op.drop_column("agents", "is_active")
    op.drop_column("agents", "password_hash")
    op.drop_column("agents", "email")
