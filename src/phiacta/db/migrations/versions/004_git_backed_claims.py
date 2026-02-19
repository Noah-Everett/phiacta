# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Git-backed claims: restructure claims, simplify interactions, add outbox
and references.

Revision ID: 004
Revises: 003
Create Date: 2026-02-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: str = "003"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Drop views that reference old columns
    # ------------------------------------------------------------------
    op.execute("DROP VIEW IF EXISTS claims_with_confidence")
    op.execute("DROP VIEW IF EXISTS claims_latest")

    # ------------------------------------------------------------------
    # 2. Alter claims table
    # ------------------------------------------------------------------

    # Add new columns first (nullable so existing rows don't break)
    op.add_column("claims", sa.Column("title", sa.Text(), nullable=True))
    op.add_column("claims", sa.Column("format", sa.String(), nullable=True))
    op.add_column("claims", sa.Column("content_cache", sa.Text(), nullable=True))
    op.add_column("claims", sa.Column("forgejo_repo_id", sa.Integer(), nullable=True))
    op.add_column(
        "claims", sa.Column("current_head_sha", sa.String(40), nullable=True)
    )
    op.add_column(
        "claims",
        sa.Column("repo_status", sa.String(), nullable=True),
    )
    op.add_column(
        "claims", sa.Column("cached_confidence", sa.Float(), nullable=True)
    )
    op.add_column(
        "claims",
        sa.Column(
            "confidence_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Populate new columns from existing data
    op.execute(
        sa.text("""
        UPDATE claims SET
            title = COALESCE(LEFT(content, 200), 'Untitled'),
            format = 'markdown',
            content_cache = content,
            repo_status = 'provisioning'
        """)
    )

    # Make title NOT NULL now that it's populated
    op.alter_column("claims", "title", nullable=False)

    # Update status constraint: replace 'deprecated' with 'archived'
    # The original constraint was created inline via raw SQL in 001 without
    # an explicit name, so PostgreSQL auto-named it "claims_status_check".
    op.drop_constraint("claims_status_check", "claims", type_="check")
    op.execute(
        sa.text(
            "UPDATE claims SET status = 'archived' WHERE status = 'deprecated'"
        )
    )
    op.create_check_constraint(
        "ck_claims_status",
        "claims",
        "status IN ('draft', 'active', 'archived', 'retracted')",
    )

    # Add repo_status constraint
    op.create_check_constraint(
        "ck_claims_repo_status",
        "claims",
        "repo_status IN ('provisioning', 'ready', 'error')",
    )

    # Drop old columns
    op.drop_index("idx_claims_lineage", table_name="claims")
    op.drop_constraint("claims_lineage_id_version_key", "claims", type_="unique")
    op.drop_constraint("claims_supersedes_fkey", "claims", type_="foreignkey")
    op.drop_column("claims", "lineage_id")
    op.drop_column("claims", "version")
    op.drop_column("claims", "supersedes")
    op.drop_column("claims", "formal_content")
    op.drop_column("claims", "content")

    # idx_claims_active already exists from migration 001 — no need to recreate.

    # ------------------------------------------------------------------
    # 3. Alter interactions table
    # ------------------------------------------------------------------

    # Drop interaction_references table (no longer used)
    op.drop_table("interaction_references")

    # Drop parent_id column and related indexes
    op.drop_index("idx_interactions_parent", table_name="interactions")
    op.drop_constraint("interactions_parent_id_fkey", "interactions", type_="foreignkey")
    op.drop_column("interactions", "parent_id")

    # Update kind constraint to votes + reviews only
    op.drop_constraint("ck_interactions_kind", "interactions", type_="check")
    op.create_check_constraint(
        "ck_interactions_kind",
        "interactions",
        "kind IN ('vote', 'review')",
    )

    # Update body_required constraint
    op.drop_constraint("ck_interactions_body_required", "interactions", type_="check")
    op.create_check_constraint(
        "ck_interactions_body_required",
        "interactions",
        "kind != 'review' OR body IS NOT NULL",
    )

    # Delete any non-vote/review interactions
    op.execute(
        sa.text(
            "DELETE FROM interactions WHERE kind NOT IN ('vote', 'review')"
        )
    )

    # Drop attrs GIN index (will be recreated if needed)
    op.drop_index("idx_interactions_attrs", table_name="interactions")

    # ------------------------------------------------------------------
    # 4. Create outbox table
    # ------------------------------------------------------------------
    op.create_table(
        "outbox",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
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
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column(
            "payload",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "attempts", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "max_attempts", sa.Integer(), nullable=False, server_default="5"
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_outbox_status",
        ),
    )
    op.create_index(
        "idx_outbox_pending",
        "outbox",
        ["created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    # ------------------------------------------------------------------
    # 5. Create references table
    # ------------------------------------------------------------------
    op.create_table(
        "references",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
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
        sa.Column("source_uri", sa.String(), nullable=False),
        sa.Column("target_uri", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey("agents.id"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("source_claim_id", sa.Uuid(), nullable=True),
        sa.Column("target_claim_id", sa.Uuid(), nullable=True),
    )
    op.create_index("idx_references_source_uri", "references", ["source_uri"])
    op.create_index("idx_references_target_uri", "references", ["target_uri"])
    op.create_index(
        "idx_references_source_claim", "references", ["source_claim_id"]
    )
    op.create_index(
        "idx_references_target_claim", "references", ["target_claim_id"]
    )
    op.create_index(
        "idx_references_source_type", "references", ["source_type"]
    )
    op.create_index(
        "idx_references_target_type", "references", ["target_type"]
    )

    # ------------------------------------------------------------------
    # 6. Migrate existing relations to references
    # ------------------------------------------------------------------
    op.execute(
        sa.text("""
        INSERT INTO "references" (
            id, created_at, updated_at,
            source_uri, target_uri, role, created_by,
            source_type, target_type, source_claim_id, target_claim_id
        )
        SELECT
            id, created_at, updated_at,
            'claim:' || source_id, 'claim:' || target_id,
            relation_type, created_by,
            'claim', 'claim', source_id, target_id
        FROM relations
        """)
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS claims_with_confidence")

    # Drop new tables
    op.drop_table("references")
    op.drop_table("outbox")

    # Restore interactions parent_id column
    op.add_column(
        "interactions",
        sa.Column(
            "parent_id",
            sa.Uuid(),
            sa.ForeignKey("interactions.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_interactions_parent",
        "interactions",
        ["parent_id"],
        postgresql_where=sa.text("parent_id IS NOT NULL"),
    )

    # Restore 5-kind constraint
    op.drop_constraint("ck_interactions_kind", "interactions", type_="check")
    op.create_check_constraint(
        "ck_interactions_kind",
        "interactions",
        "kind IN ('comment', 'vote', 'review', 'issue', 'suggestion')",
    )

    # Restore body_required constraint
    op.drop_constraint("ck_interactions_body_required", "interactions", type_="check")
    op.create_check_constraint(
        "ck_interactions_body_required",
        "interactions",
        "kind NOT IN ('comment', 'review', 'issue', 'suggestion') OR body IS NOT NULL",
    )

    # Recreate interaction_references table
    op.create_table(
        "interaction_references",
        sa.Column(
            "interaction_id",
            sa.Uuid(),
            sa.ForeignKey("interactions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("ref_type", sa.String(), primary_key=True),
        sa.Column("ref_id", sa.Uuid(), primary_key=True),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column(
            "attrs",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
    )

    # Restore claims columns
    op.add_column("claims", sa.Column("content", sa.Text(), nullable=True))
    op.add_column("claims", sa.Column("formal_content", sa.Text(), nullable=True))
    op.add_column("claims", sa.Column("lineage_id", sa.Uuid(), nullable=True))
    op.add_column(
        "claims",
        sa.Column("version", sa.Integer(), nullable=True, server_default="1"),
    )
    op.add_column(
        "claims",
        sa.Column(
            "supersedes",
            sa.Uuid(),
            sa.ForeignKey("claims.id"),
            nullable=True,
        ),
    )

    # Copy content_cache back to content
    op.execute(sa.text("UPDATE claims SET content = content_cache"))

    # Drop new claims columns
    op.drop_constraint("ck_claims_repo_status", "claims", type_="check")
    op.drop_column("claims", "title")
    op.drop_column("claims", "format")
    op.drop_column("claims", "content_cache")
    op.drop_column("claims", "forgejo_repo_id")
    op.drop_column("claims", "current_head_sha")
    op.drop_column("claims", "repo_status")
    op.drop_column("claims", "cached_confidence")
    op.drop_column("claims", "confidence_updated_at")

    # Restore status constraint
    op.drop_constraint("ck_claims_status", "claims", type_="check")
    op.create_check_constraint(
        "ck_claims_status",
        "claims",
        "status IN ('draft', 'active', 'deprecated', 'retracted')",
    )

    # Recreate claims_latest view
    op.execute(
        """
        CREATE VIEW claims_latest AS
        SELECT DISTINCT ON (lineage_id) *
        FROM claims
        WHERE status IN ('active', 'draft')
        ORDER BY lineage_id, version DESC
        """
    )
