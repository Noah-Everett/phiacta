# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Create view_versions table.

Revision ID: 002
Revises: 001
Create Date: 2026-03-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "view_versions",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("view_type", sa.String(50), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "parameters",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "uq_view_versions_type_version",
        "view_versions",
        ["view_type", "version"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("view_versions")
