# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Replace status + schema_version with visibility.

Adds visibility column, populates from status (archived → private,
everything else → public), drops status and schema_version columns,
and replaces the partial index.

Revision ID: 010
Revises: 009
Create Date: 2026-03-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: str | None = "009"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # 1. Add visibility column with default
    op.add_column(
        "entries",
        sa.Column("visibility", sa.String(20), nullable=False, server_default="public"),
    )

    # 2. Populate visibility from status
    op.execute("UPDATE entries SET visibility = 'private' WHERE status = 'archived'")
    op.execute("UPDATE entries SET visibility = 'public' WHERE status != 'archived'")

    # 3. Drop the old partial index that depends on status
    op.drop_index("idx_entries_active", table_name="entries")

    # 4. Drop status and schema_version columns
    op.drop_column("entries", "status")
    op.drop_column("entries", "schema_version")

    # 5. Create new partial index on visibility
    op.create_index(
        "idx_entries_public",
        "entries",
        ["visibility"],
        postgresql_where=sa.text("visibility = 'public'"),
    )


def downgrade() -> None:
    # Drop new index
    op.drop_index("idx_entries_public", table_name="entries")

    # Re-add status and schema_version
    op.add_column(
        "entries",
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
    )
    op.add_column(
        "entries",
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
    )

    # Populate status from visibility
    op.execute("UPDATE entries SET status = 'archived' WHERE visibility = 'private'")
    op.execute("UPDATE entries SET status = 'active' WHERE visibility = 'public'")

    # Re-create old partial index
    op.create_index(
        "idx_entries_active",
        "entries",
        ["status"],
        postgresql_where=sa.text("status = 'active'"),
    )

    # Drop visibility
    op.drop_column("entries", "visibility")
