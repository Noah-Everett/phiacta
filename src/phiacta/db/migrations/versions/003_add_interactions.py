# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Replace reviews with unified interactions system.

Creates interactions and interaction_references tables. Migrates existing
review data into interactions. Drops the old claims_with_confidence view
so the confidence layer can recreate it against the new table on startup.

Revision ID: 003
Revises: 002
Create Date: 2026-02-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: str = "002"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Create interactions table
    # ------------------------------------------------------------------
    op.create_table(
        "interactions",
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "claim_id",
            sa.Uuid(),
            sa.ForeignKey("claims.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            sa.Uuid(),
            sa.ForeignKey("agents.id"),
            nullable=False,
        ),
        sa.Column(
            "parent_id",
            sa.Uuid(),
            sa.ForeignKey("interactions.id"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("signal", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("author_trust_snapshot", sa.Float(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("origin_uri", sa.Text(), nullable=True),
        sa.Column(
            "attrs",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        # CHECK constraints
        sa.CheckConstraint(
            "kind IN ('comment', 'vote', 'review', 'issue', 'suggestion')",
            name="ck_interactions_kind",
        ),
        sa.CheckConstraint(
            "signal IS NULL OR signal IN ('agree', 'disagree', 'neutral')",
            name="ck_interactions_signal",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)",
            name="ck_interactions_confidence",
        ),
        sa.CheckConstraint(
            "(signal IS NULL AND confidence IS NULL)"
            " OR (signal IS NOT NULL AND confidence IS NOT NULL)",
            name="ck_interactions_signal_confidence",
        ),
        sa.CheckConstraint(
            "kind != 'vote' OR signal IS NOT NULL",
            name="ck_interactions_vote_signal",
        ),
        sa.CheckConstraint(
            "kind NOT IN ('comment', 'review', 'issue', 'suggestion')"
            " OR body IS NOT NULL",
            name="ck_interactions_body_required",
        ),
    )

    # Indexes
    op.create_index("idx_interactions_claim", "interactions", ["claim_id"])
    op.create_index(
        "idx_interactions_parent",
        "interactions",
        ["parent_id"],
        postgresql_where=sa.text("parent_id IS NOT NULL"),
    )
    op.create_index("idx_interactions_author", "interactions", ["author_id"])
    op.create_index(
        "idx_interactions_claim_signal",
        "interactions",
        ["claim_id", "signal", "confidence"],
        postgresql_where=sa.text("signal IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "idx_interactions_claim_kind",
        "interactions",
        ["claim_id", "kind"],
    )
    op.create_index(
        "idx_interactions_attrs",
        "interactions",
        ["attrs"],
        postgresql_using="gin",
    )
    # Partial unique index: one active signal per agent per claim
    op.create_index(
        "uq_interactions_claim_author_signal",
        "interactions",
        ["claim_id", "author_id"],
        unique=True,
        postgresql_where=sa.text("signal IS NOT NULL AND deleted_at IS NULL"),
    )

    # ------------------------------------------------------------------
    # 2. Create interaction_references table
    # ------------------------------------------------------------------
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
        sa.CheckConstraint(
            "ref_type IN ('claim', 'source', 'artifact')",
            name="ck_interaction_references_ref_type",
        ),
        sa.CheckConstraint(
            "role IN ('evidence', 'citation', 'rebuttal', 'context',"
            " 'method', 'corroboration', 'dataset')",
            name="ck_interaction_references_role",
        ),
    )
    op.create_index(
        "idx_interaction_references_ref",
        "interaction_references",
        ["ref_type", "ref_id"],
    )

    # ------------------------------------------------------------------
    # 3. Migrate existing reviews into interactions
    # ------------------------------------------------------------------
    op.execute(
        sa.text("""
        INSERT INTO interactions (
            id, created_at, updated_at, claim_id, author_id, kind,
            signal, confidence, weight, body, attrs
        )
        SELECT
            id,
            created_at,
            updated_at,
            claim_id,
            reviewer_id,
            CASE
                WHEN comment IS NOT NULL THEN 'review'
                ELSE 'vote'
            END,
            CASE verdict
                WHEN 'endorse' THEN 'agree'
                WHEN 'dispute' THEN 'disagree'
                WHEN 'neutral' THEN 'neutral'
                ELSE verdict
            END,
            confidence,
            1.0,
            comment,
            '{}'::jsonb
        FROM reviews
        """)
    )

    # ------------------------------------------------------------------
    # 4. Drop the old claims_with_confidence view so the confidence
    #    layer can recreate it on startup with the new schema.
    # ------------------------------------------------------------------
    op.execute(sa.text("DROP VIEW IF EXISTS claims_with_confidence"))


def downgrade() -> None:
    op.execute(sa.text("DROP VIEW IF EXISTS claims_with_confidence"))
    op.drop_table("interaction_references")
    op.drop_table("interactions")
