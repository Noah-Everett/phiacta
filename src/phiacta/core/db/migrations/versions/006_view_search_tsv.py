# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Create view_search_tsv table for full-text search.

Revision ID: 006
Revises: 005
Create Date: 2026-03-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

revision: str = "006"
down_revision: str | None = "005"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "view_search_tsv",
        sa.Column(
            "entry_id",
            sa.Uuid(),
            sa.ForeignKey("entries.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "version_id",
            sa.Uuid(),
            sa.ForeignKey("view_versions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("tsv", TSVECTOR(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_view_search_tsv_gin",
        "view_search_tsv",
        ["tsv"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_table("view_search_tsv")
