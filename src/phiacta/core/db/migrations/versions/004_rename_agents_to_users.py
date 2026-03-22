# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Rename agents -> users, drop agent_type/is_active/email columns.

NEV-227: Simplify the account model. The agent_type distinction doesn't
belong on the account level, is_active and email are unused.

Revision ID: 004
Revises: 003
Create Date: 2026-03-21
"""

from __future__ import annotations

from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # Rename the table
    op.rename_table("agents", "users")

    # Drop unused columns
    op.drop_column("users", "agent_type")
    op.drop_column("users", "is_active")
    op.drop_column("users", "email")

    # Rename indexes
    op.execute("ALTER INDEX idx_agents_handle RENAME TO idx_users_handle")
    op.execute("DROP INDEX IF EXISTS idx_agents_email")

    # Update FK on entries.created_by to point to users
    op.drop_constraint(
        "entries_created_by_fkey", "entries", type_="foreignkey",
    )
    op.create_foreign_key(
        "entries_created_by_fkey", "entries", "users",
        ["created_by"], ["id"],
    )

    # Update FK on extension_tags.created_by to point to users
    op.drop_constraint(
        "extension_tags_created_by_fkey", "extension_tags", type_="foreignkey",
    )
    op.create_foreign_key(
        "extension_tags_created_by_fkey", "extension_tags", "users",
        ["created_by"], ["id"],
    )


def downgrade() -> None:
    import sqlalchemy as sa

    # Restore FK on extension_tags
    op.drop_constraint(
        "extension_tags_created_by_fkey", "extension_tags", type_="foreignkey",
    )
    op.create_foreign_key(
        "extension_tags_created_by_fkey", "extension_tags", "agents",
        ["created_by"], ["id"],
    )

    # Restore FK on entries
    op.drop_constraint(
        "entries_created_by_fkey", "entries", type_="foreignkey",
    )
    op.create_foreign_key(
        "entries_created_by_fkey", "entries", "agents",
        ["created_by"], ["id"],
    )

    # Restore index
    op.execute("ALTER INDEX idx_users_handle RENAME TO idx_agents_handle")

    # Re-add dropped columns
    op.add_column(
        "users",
        sa.Column("email", sa.String(254), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default="true",
        ),
    )
    op.add_column(
        "users",
        sa.Column("agent_type", sa.String(20), nullable=True),
    )
    op.create_index("idx_agents_email", "users", ["email"], unique=True)

    # Rename table back
    op.rename_table("users", "agents")
