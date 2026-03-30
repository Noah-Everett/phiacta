# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Add explicit ON DELETE behavior to FK columns that lack it.

Drops and recreates each FK constraint with the appropriate ondelete
clause: RESTRICT for columns that should block parent deletion, SET NULL
for optional parent references.

Revision ID: 011
Revises: 010
Create Date: 2026-03-30
"""

from __future__ import annotations

from alembic import op

revision: str = "011"
down_revision: str | None = "010"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

# (constraint_name, source_table, ref_table, local_cols, remote_cols, ondelete)
_FK_SPECS: list[tuple[str, str, str, list[str], list[str], str]] = [
    ("entries_created_by_fkey", "entries", "users", ["created_by"], ["id"], "RESTRICT"),
    ("entities_parent_id_fkey", "entities", "entities", ["parent_id"], ["id"], "SET NULL"),
    ("entities_created_by_fkey", "entities", "entities", ["created_by"], ["id"], "SET NULL"),
    ("activity_actor_id_fkey", "activity", "entities", ["actor_id"], ["id"], "RESTRICT"),
    ("activity_entity_id_fkey", "activity", "entities", ["entity_id"], ["id"], "RESTRICT"),
    ("extension_metadata_created_by_fkey", "extension_metadata", "users", ["created_by"], ["id"], "RESTRICT"),
    ("extension_types_created_by_fkey", "extension_types", "users", ["created_by"], ["id"], "RESTRICT"),
    ("extension_references_created_by_fkey", "extension_references", "users", ["created_by"], ["id"], "RESTRICT"),
    ("extension_tags_created_by_fkey", "extension_tags", "users", ["created_by"], ["id"], "RESTRICT"),
]


def upgrade() -> None:
    for constraint, table, ref_table, local_cols, remote_cols, ondelete in _FK_SPECS:
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.create_foreign_key(
            constraint, table, ref_table, local_cols, remote_cols, ondelete=ondelete,
        )


def downgrade() -> None:
    for constraint, table, ref_table, local_cols, remote_cols, _ondelete in reversed(_FK_SPECS):
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.create_foreign_key(
            constraint, table, ref_table, local_cols, remote_cols,
        )
