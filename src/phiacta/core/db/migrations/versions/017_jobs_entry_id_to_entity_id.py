# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Rename jobs.entry_id → entity_id; change FK from entries to entities.

Jobs are a general-purpose mechanism not specific to entries.  The column
is renamed to entity_id and re-pointed at the entity registry so any
entity type can be associated with a job.

Revision ID: 017
Revises: 016
"""

from alembic import op

revision: str = "017"
down_revision: str | None = "016"
branch_labels: tuple | None = None
depends_on: tuple | None = None


def upgrade() -> None:
    op.drop_constraint("jobs_entry_id_fkey", "jobs", type_="foreignkey")
    op.alter_column("jobs", "entry_id", new_column_name="entity_id")
    op.create_foreign_key(
        "jobs_entity_id_fkey",
        "jobs",
        "entities",
        ["entity_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("jobs_entity_id_fkey", "jobs", type_="foreignkey")
    op.alter_column("jobs", "entity_id", new_column_name="entry_id")
    op.create_foreign_key(
        "jobs_entry_id_fkey",
        "jobs",
        "entries",
        ["entry_id"],
        ["id"],
        ondelete="SET NULL",
    )
