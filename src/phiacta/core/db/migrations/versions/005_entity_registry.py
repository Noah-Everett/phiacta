# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Add entities and activity tables, migrate tags FK.

NEV-228/229/230: Entity registry — universal ID layer for all objects,
activity log for user feeds.

Revision ID: 005
Revises: 004
Create Date: 2026-03-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # --- entities table ---
    op.create_table(
        "entities",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("parent_id", sa.Uuid(), sa.ForeignKey("entities.id"), nullable=True),
        sa.Column("external_ref", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("entities.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_entities_type", "entities", ["entity_type"])
    op.create_index("idx_entities_parent", "entities", ["parent_id"])
    op.create_index("idx_entities_created_by", "entities", ["created_by"])
    op.create_index(
        "idx_entities_parent_ref",
        "entities",
        ["parent_id", "external_ref"],
        unique=True,
        postgresql_where=sa.text("external_ref IS NOT NULL"),
    )

    # --- Backfill existing users into entities ---
    op.execute("""
        INSERT INTO entities (id, entity_type, parent_id, external_ref, created_by, created_at)
        SELECT id, 'user', NULL, NULL, NULL, created_at
        FROM users
    """)

    # --- Backfill existing entries into entities ---
    op.execute("""
        INSERT INTO entities (id, entity_type, parent_id, external_ref, created_by, created_at)
        SELECT id, 'entry', NULL, NULL, created_by, created_at
        FROM entries
    """)

    # --- activity table ---
    op.create_table(
        "activity",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.Uuid(), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_activity_actor", "activity", ["actor_id", sa.text("created_at DESC")])
    op.create_index("idx_activity_entity", "activity", ["entity_id", sa.text("created_at DESC")])

    # --- Migrate extension_tags FK from entries.id to entities.id ---
    op.drop_constraint("extension_tags_entry_id_fkey", "extension_tags", type_="foreignkey")
    op.alter_column("extension_tags", "entry_id", new_column_name="entity_id")
    op.create_foreign_key(
        "extension_tags_entity_id_fkey",
        "extension_tags",
        "entities",
        ["entity_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # Update unique constraint name
    op.drop_constraint("uq_extension_tags_entry_tag", "extension_tags", type_="unique")
    op.create_unique_constraint("uq_extension_tags_entity_tag", "extension_tags", ["entity_id", "tag"])
    # Update index
    op.drop_index("ix_extension_tags_entry_id", "extension_tags")
    op.create_index("ix_extension_tags_entity_id", "extension_tags", ["entity_id"])


def downgrade() -> None:
    # Reverse tags migration
    op.drop_index("ix_extension_tags_entity_id", "extension_tags")
    op.drop_constraint("uq_extension_tags_entity_tag", "extension_tags", type_="unique")
    op.drop_constraint("extension_tags_entity_id_fkey", "extension_tags", type_="foreignkey")
    op.alter_column("extension_tags", "entity_id", new_column_name="entry_id")
    op.create_foreign_key(
        "extension_tags_entry_id_fkey",
        "extension_tags",
        "entries",
        ["entry_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint("uq_extension_tags_entry_tag", "extension_tags", ["entry_id", "tag"])
    op.create_index("ix_extension_tags_entry_id", "extension_tags", ["entry_id"])

    op.drop_table("activity")
    op.drop_table("entities")
