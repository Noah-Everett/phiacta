# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Entry minimization — strip entries to identity + git plumbing.

Creates extension_metadata, extension_types, extension_references tables.
Drops title, summary, license, layout_hint, content_format, content_cache
columns from entries. Drops the entry_refs table.

No data migration — system is wiped and rebuilt fresh.

Revision ID: 008
Revises: 007
"""

from alembic import op
import sqlalchemy as sa

revision: str = "008"
down_revision: str | None = "007"
branch_labels: tuple | None = None
depends_on: tuple | None = None


def upgrade() -> None:
    # --- Create extension_metadata ---
    op.create_table(
        "extension_metadata",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.UniqueConstraint("entity_id", name="uq_extension_metadata_entity"),
    )
    op.create_index("ix_extension_metadata_entity_id", "extension_metadata", ["entity_id"])

    # --- Create extension_types ---
    op.create_table(
        "extension_types",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("entry_type", sa.String(100), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.UniqueConstraint("entity_id", name="uq_extension_types_entity"),
    )
    op.create_index("ix_extension_types_entity_id", "extension_types", ["entity_id"])

    # --- Create extension_references ---
    op.create_table(
        "extension_references",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("from_entity_id", sa.Uuid(), nullable=False),
        sa.Column("to_entity_id", sa.Uuid(), nullable=False),
        sa.Column("rel", sa.String(50), nullable=False),
        sa.Column("version_sha", sa.String(40), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["from_entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.CheckConstraint("from_entity_id != to_entity_id", name="ck_extension_references_no_self_ref"),
        sa.UniqueConstraint("from_entity_id", "to_entity_id", "rel", name="uq_extension_references_from_to_rel"),
    )
    op.create_index("ix_extension_references_from", "extension_references", ["from_entity_id"])
    op.create_index("ix_extension_references_to", "extension_references", ["to_entity_id"])
    op.create_index("ix_extension_references_rel", "extension_references", ["rel"])

    # --- Drop columns from entries ---
    op.drop_index("idx_entries_layout_hint", table_name="entries")
    op.drop_column("entries", "title")
    op.drop_column("entries", "layout_hint")
    op.drop_column("entries", "summary")
    op.drop_column("entries", "license")
    op.drop_column("entries", "content_format")
    op.drop_column("entries", "content_cache")

    # --- Drop entry_refs table ---
    op.drop_table("entry_refs")


def downgrade() -> None:
    op.create_table(
        "entry_refs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("from_entry_id", sa.Uuid(), nullable=False),
        sa.Column("to_entry_id", sa.Uuid(), nullable=False),
        sa.Column("rel", sa.String(50), nullable=False),
        sa.Column("version_sha", sa.String(40), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["from_entry_id"], ["entries.id"]),
        sa.ForeignKeyConstraint(["to_entry_id"], ["entries.id"]),
    )
    op.add_column("entries", sa.Column("title", sa.String(500), nullable=False, server_default=""))
    op.add_column("entries", sa.Column("layout_hint", sa.String(50), nullable=True))
    op.add_column("entries", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column("entries", sa.Column("license", sa.String(50), nullable=True))
    op.add_column("entries", sa.Column("content_format", sa.String(20), nullable=False, server_default="markdown"))
    op.add_column("entries", sa.Column("content_cache", sa.Text(), nullable=True))
    op.drop_table("extension_references")
    op.drop_table("extension_types")
    op.drop_table("extension_metadata")
