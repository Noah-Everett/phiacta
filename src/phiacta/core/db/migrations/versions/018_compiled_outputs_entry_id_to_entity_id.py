# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Rename compiled_outputs.entry_id → entity_id; update unique constraint.

Aligns naming with every other extension table that references entities.

Revision ID: 018
Revises: 017
"""

from alembic import op

revision: str = "018"
down_revision: str | None = "017"
branch_labels: tuple | None = None
depends_on: tuple | None = None


def upgrade() -> None:
    op.drop_constraint("uq_compiled_outputs_entry_format", "compiled_outputs", type_="unique")
    op.drop_constraint("compiled_outputs_entry_id_fkey", "compiled_outputs", type_="foreignkey")
    op.alter_column("compiled_outputs", "entry_id", new_column_name="entity_id")
    op.create_foreign_key(
        "compiled_outputs_entity_id_fkey",
        "compiled_outputs",
        "entities",
        ["entity_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_compiled_outputs_entity_format",
        "compiled_outputs",
        ["entity_id", "format"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_compiled_outputs_entity_format", "compiled_outputs", type_="unique")
    op.drop_constraint("compiled_outputs_entity_id_fkey", "compiled_outputs", type_="foreignkey")
    op.alter_column("compiled_outputs", "entity_id", new_column_name="entry_id")
    op.create_foreign_key(
        "compiled_outputs_entry_id_fkey",
        "compiled_outputs",
        "entities",
        ["entry_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_compiled_outputs_entry_format",
        "compiled_outputs",
        ["entry_id", "format"],
    )
