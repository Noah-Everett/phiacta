# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Migrate view_search_tsv from entry_id to entity_id.

Renames the column and swaps the FK from entries.id to entities.id.
Since entry.id == entity.id (entries are created with the entity UUID),
no data migration is needed — all existing values already exist in entities.

Revision ID: 014
Revises: 013
"""

from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None

# The FK constraint name assigned by PostgreSQL during table creation.
# Convention: {table}_{column}_fkey
_OLD_FK = "view_search_tsv_entry_id_fkey"
_NEW_FK = "view_search_tsv_entity_id_fkey"


def upgrade() -> None:
    # Drop the old FK to entries.id
    op.drop_constraint(_OLD_FK, "view_search_tsv", type_="foreignkey")

    # Rename the column
    op.alter_column("view_search_tsv", "entry_id", new_column_name="entity_id")

    # Add new FK to entities.id
    op.create_foreign_key(
        _NEW_FK,
        "view_search_tsv",
        "entities",
        ["entity_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(_NEW_FK, "view_search_tsv", type_="foreignkey")
    op.alter_column("view_search_tsv", "entity_id", new_column_name="entry_id")
    op.create_foreign_key(
        _OLD_FK,
        "view_search_tsv",
        "entries",
        ["entry_id"],
        ["id"],
        ondelete="CASCADE",
    )
