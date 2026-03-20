# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Drop tags column from entries, create extension_tags table.

Tags are now managed by the tags extension plugin. The entries table
must be purely repo-derived — tags are user-authored data that belongs
in the extension layer.

Revision ID: 003
Revises: 002
Create Date: 2026-03-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # Drop the tags column from entries (was violating repo-derived rule)
    op.drop_column("entries", "tags")

    # Create the extension_tags table
    op.create_table(
        "extension_tags",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "entry_id",
            sa.Uuid(),
            sa.ForeignKey("entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tag", sa.String(200), nullable=False),
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey("agents.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("entry_id", "tag", name="uq_extension_tags_entry_tag"),
    )
    op.create_index("ix_extension_tags_entry_id", "extension_tags", ["entry_id"])
    op.create_index("ix_extension_tags_tag", "extension_tags", ["tag"])


def downgrade() -> None:
    op.drop_table("extension_tags")
    op.add_column(
        "entries",
        sa.Column(
            "tags",
            sa.dialects.postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )
