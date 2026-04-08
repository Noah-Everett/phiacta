# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Create compiled_outputs table for storing compiled entry artifacts.

Revision ID: 016
Revises: 015
"""

from alembic import op
import sqlalchemy as sa

revision: str = "016"
down_revision: str | None = "015"
branch_labels: tuple | None = None
depends_on: tuple | None = None


def upgrade() -> None:
    op.create_table(
        "compiled_outputs",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("entry_id", sa.Uuid(), nullable=False),
        sa.Column("format", sa.String(10), nullable=False, server_default=sa.text("'pdf'")),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("source_sha", sa.String(40), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("compiled_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("accessed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["entry_id"], ["entities.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("entry_id", "format", name="uq_compiled_outputs_entry_format"),
    )
    op.create_index("ix_compiled_outputs_accessed", "compiled_outputs", ["accessed_at"])


def downgrade() -> None:
    op.drop_table("compiled_outputs")
