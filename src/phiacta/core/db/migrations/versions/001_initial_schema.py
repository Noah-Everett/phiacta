# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Initial schema: all tables, indexes, and constraints.

Revision ID: 001
Revises:
Create Date: 2026-03-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # PostgreSQL extensions
    # ------------------------------------------------------------------
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm"')

    # ------------------------------------------------------------------
    # 1. agents
    # ------------------------------------------------------------------
    op.create_table(
        "agents",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("handle", sa.String(50), nullable=False, unique=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(128), nullable=False),
        sa.Column("agent_type", sa.String(20), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_agents_handle", "agents", ["handle"], unique=True)
    op.create_index("idx_agents_email", "agents", ["email"], unique=True)

    # ------------------------------------------------------------------
    # 2. entries
    # ------------------------------------------------------------------
    op.create_table(
        "entries",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("layout_hint", sa.String(50), nullable=True),
        sa.Column(
            "tags",
            sa.dialects.postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("license", sa.String(50), nullable=True),
        sa.Column(
            "content_format",
            sa.String(20),
            nullable=False,
            server_default="markdown",
        ),
        sa.Column("content_cache", sa.Text(), nullable=True),
        sa.Column(
            "schema_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("forgejo_repo_id", sa.Integer(), nullable=True),
        sa.Column("repo_name", sa.String(200), nullable=False),
        sa.Column("current_head_sha", sa.String(40), nullable=True),
        sa.Column(
            "repo_status",
            sa.String(20),
            nullable=False,
            server_default="provisioning",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="active",
        ),
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_entries_active",
        "entries",
        ["status"],
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index("idx_entries_layout_hint", "entries", ["layout_hint"])
    op.create_index("idx_entries_created_by", "entries", ["created_by"])

    # ------------------------------------------------------------------
    # 3. entry_refs
    # ------------------------------------------------------------------
    op.create_table(
        "entry_refs",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "from_entry_id",
            sa.Uuid(),
            sa.ForeignKey("entries.id"),
            nullable=False,
        ),
        sa.Column(
            "to_entry_id",
            sa.Uuid(),
            sa.ForeignKey("entries.id"),
            nullable=False,
        ),
        sa.Column("rel", sa.String(50), nullable=False),
        sa.Column("version_sha", sa.String(40), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "from_entry_id != to_entry_id",
            name="ck_entry_refs_no_self_ref",
        ),
    )
    op.create_index("ix_entry_refs_from", "entry_refs", ["from_entry_id"])
    op.create_index("ix_entry_refs_to", "entry_refs", ["to_entry_id"])
    op.create_index("ix_entry_refs_rel", "entry_refs", ["rel"])

    # ------------------------------------------------------------------
    # 4. outbox
    # ------------------------------------------------------------------
    op.create_table(
        "outbox",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("aggregate_type", sa.String(30), nullable=False),
        sa.Column("operation", sa.String(50), nullable=False),
        sa.Column(
            "payload",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("process_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_outbox_poll",
        "outbox",
        ["status", "process_after"],
        postgresql_where=sa.text("status = 'pending'"),
    )



def downgrade() -> None:
    op.drop_table("outbox")
    op.drop_table("entry_refs")
    op.drop_table("entries")
    op.drop_table("agents")
    op.execute('DROP EXTENSION IF EXISTS "pg_trgm"')
    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
