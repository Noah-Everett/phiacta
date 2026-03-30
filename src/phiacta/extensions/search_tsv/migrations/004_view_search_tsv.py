# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Create view_search_tsv table and seed initial version.

Creates the precomputed tsvector table with composite PK (entry_id, version_id),
GIN index on the tsv column, and seeds the initial view_versions row for
search_tsv v1.

Revision ID: 004
Revises: 003
Create Date: 2026-03-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # Create the view_search_tsv table
    op.create_table(
        "view_search_tsv",
        sa.Column(
            "entry_id",
            sa.Uuid(),
            sa.ForeignKey("entries.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "version_id",
            sa.Uuid(),
            sa.ForeignKey("view_versions.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "tsv",
            sa.dialects.postgresql.TSVECTOR(),
            nullable=False,
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # GIN index on the tsvector column for fast full-text search
    op.execute(
        "CREATE INDEX ix_view_search_tsv_gin "
        "ON view_search_tsv USING gin(tsv)"
    )

    # Seed the initial view_versions row for search_tsv v1.
    # Requires uuid-ossp extension (installed in migration 001).
    op.execute(
        "INSERT INTO view_versions (id, view_type, version, status, parameters) "
        "VALUES ("
        "  uuid_generate_v4(), "
        "  'search_tsv', "
        "  'v1', "
        "  'active', "
        "  '{\"language\": \"english\"}'::jsonb"
        ")"
    )


def downgrade() -> None:
    # Remove the seeded version row
    op.execute(
        "DELETE FROM view_versions "
        "WHERE view_type = 'search_tsv' AND version = 'v1'"
    )

    # Drop the table (index is dropped automatically with the table)
    op.drop_table("view_search_tsv")
