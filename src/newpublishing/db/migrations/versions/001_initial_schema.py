# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NewPublishing Contributors

"""Initial schema: all core tables, indexes, seed data, and views.

Revision ID: 001
Revises:
Create Date: 2026-02-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Enable PostgreSQL extensions
    # ------------------------------------------------------------------
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "vector"')

    # ------------------------------------------------------------------
    # 1. agents (no deps)
    # ------------------------------------------------------------------
    op.create_table(
        "agents",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column(
            "agent_type",
            sa.Text(),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("trust_score", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("api_key_hash", sa.Text(), nullable=True),
        sa.Column("attrs", sa.JSON(), nullable=False, server_default="{}"),
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
        sa.CheckConstraint(
            "agent_type IN ('human', 'ai', 'organization', 'pipeline', 'extension')",
            name="ck_agents_agent_type",
        ),
    )
    op.create_index(
        "idx_agents_external_id",
        "agents",
        ["external_id"],
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )

    # ------------------------------------------------------------------
    # 2. namespaces (self-referential)
    # ------------------------------------------------------------------
    op.create_table(
        "namespaces",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), sa.ForeignKey("namespaces.id"), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("attrs", sa.JSON(), nullable=False, server_default="{}"),
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
    op.create_index("idx_namespaces_parent", "namespaces", ["parent_id"])

    # ------------------------------------------------------------------
    # 3. sources (depends on agents)
    # ------------------------------------------------------------------
    op.create_table(
        "sources",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("external_ref", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("submitted_by", sa.Uuid(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("attrs", sa.JSON(), nullable=False, server_default="{}"),
        sa.CheckConstraint(
            "source_type IN ("
            "'paper', 'preprint', 'recording', 'photo', 'conversation', "
            "'code', 'dataset', 'url', 'manual_entry')",
            name="ck_sources_source_type",
        ),
    )
    op.create_index(
        "idx_sources_external_ref",
        "sources",
        ["external_ref"],
        postgresql_where=sa.text("external_ref IS NOT NULL"),
    )
    op.create_index(
        "idx_sources_content_hash",
        "sources",
        ["content_hash"],
        postgresql_where=sa.text("content_hash IS NOT NULL"),
    )

    # ------------------------------------------------------------------
    # 4. claims (depends on namespaces, agents)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE claims (
            id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            claim_type      TEXT NOT NULL CHECK (claim_type IN (
                'assertion', 'definition', 'theorem', 'conjecture',
                'observation', 'method', 'question'
            )),
            content         TEXT NOT NULL,
            formal_content  TEXT,
            namespace_id    UUID NOT NULL REFERENCES namespaces(id),
            created_by      UUID NOT NULL REFERENCES agents(id),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            lineage_id      UUID NOT NULL,
            version         INT NOT NULL DEFAULT 1,
            supersedes      UUID REFERENCES claims(id),
            status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN (
                'draft', 'active', 'deprecated', 'retracted'
            )),
            embedding       vector(1536),
            search_tsv      TSVECTOR,
            attrs           JSONB NOT NULL DEFAULT '{}',
            UNIQUE (lineage_id, version)
        )
        """
    )
    op.execute("CREATE INDEX idx_claims_lineage ON claims(lineage_id, version DESC)")
    op.execute("CREATE INDEX idx_claims_namespace ON claims(namespace_id)")
    op.execute("CREATE INDEX idx_claims_created_by ON claims(created_by)")
    op.execute(
        "CREATE INDEX idx_claims_embedding ON claims USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
    op.execute("CREATE INDEX idx_claims_search_tsv ON claims USING gin(search_tsv)")
    op.execute("CREATE INDEX idx_claims_attrs ON claims USING gin(attrs)")
    op.execute("CREATE INDEX idx_claims_active ON claims(status) WHERE status = 'active'")

    # ------------------------------------------------------------------
    # 5. edge_types (no deps)
    # ------------------------------------------------------------------
    op.create_table(
        "edge_types",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("inverse_name", sa.Text(), nullable=True),
        sa.Column("is_transitive", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_symmetric", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("category", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "category IN ('evidential', 'logical', 'structural', 'editorial')",
            name="ck_edge_types_category",
        ),
    )

    # ------------------------------------------------------------------
    # 6. edges (depends on claims, edge_types, agents, sources)
    # ------------------------------------------------------------------
    op.create_table(
        "edges",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("target_id", sa.Uuid(), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("edge_type", sa.Text(), sa.ForeignKey("edge_types.name"), nullable=False),
        sa.Column("strength", sa.Float(), nullable=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("agents.id"), nullable=False),
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
        sa.Column("source_provenance", sa.Uuid(), sa.ForeignKey("sources.id"), nullable=True),
        sa.Column("attrs", sa.JSON(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("source_id", "target_id", "edge_type", "created_by"),
        sa.CheckConstraint(
            "strength >= 0.0 AND strength <= 1.0",
            name="ck_edges_strength",
        ),
    )
    op.create_index("idx_edges_source", "edges", ["source_id"])
    op.create_index("idx_edges_target", "edges", ["target_id"])
    op.create_index("idx_edges_type", "edges", ["edge_type"])

    # ------------------------------------------------------------------
    # 7. provenance (depends on claims, sources, agents)
    # ------------------------------------------------------------------
    op.create_table(
        "provenance",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("claim_id", sa.Uuid(), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("extracted_by", sa.Uuid(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("extraction_method", sa.Text(), nullable=True),
        sa.Column("location_in_source", sa.Text(), nullable=True),
        sa.Column(
            "extracted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("attrs", sa.JSON(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("claim_id", "source_id", "extracted_by"),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_provenance_confidence",
        ),
    )
    op.create_index("idx_provenance_claim", "provenance", ["claim_id"])
    op.create_index("idx_provenance_source", "provenance", ["source_id"])

    # ------------------------------------------------------------------
    # 8. reviews (depends on claims, agents)
    # ------------------------------------------------------------------
    op.create_table(
        "reviews",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("claim_id", sa.Uuid(), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
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
        sa.UniqueConstraint("claim_id", "reviewer_id"),
        sa.CheckConstraint(
            "verdict IN ('endorse', 'dispute', 'request_revision', 'retract')",
            name="ck_reviews_verdict",
        ),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_reviews_confidence",
        ),
    )
    op.create_index("idx_reviews_claim", "reviews", ["claim_id"])
    op.create_index("idx_reviews_reviewer", "reviews", ["reviewer_id"])

    # ------------------------------------------------------------------
    # 9. bundles (depends on agents)
    # ------------------------------------------------------------------
    op.create_table(
        "bundles",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column("submitted_by", sa.Uuid(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("extension_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="accepted"),
        sa.Column("claim_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("edge_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("artifact_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("attrs", sa.JSON(), nullable=False, server_default="{}"),
        sa.CheckConstraint(
            "status IN ('accepted', 'rejected', 'processing')",
            name="ck_bundles_status",
        ),
    )

    # ------------------------------------------------------------------
    # 10. artifacts (depends on bundles)
    # ------------------------------------------------------------------
    op.create_table(
        "artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bundle_id", sa.Uuid(), sa.ForeignKey("bundles.id"), nullable=True),
        sa.Column("artifact_type", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("storage_ref", sa.Text(), nullable=True),
        sa.Column("content_inline", sa.Text(), nullable=True),
        sa.Column("structured_data", sa.JSON(), nullable=True),
        sa.Column("attrs", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ------------------------------------------------------------------
    # 11. artifact_claims (depends on artifacts, claims)
    # ------------------------------------------------------------------
    op.create_table(
        "artifact_claims",
        sa.Column("artifact_id", sa.Uuid(), sa.ForeignKey("artifacts.id"), primary_key=True),
        sa.Column("claim_id", sa.Uuid(), sa.ForeignKey("claims.id"), primary_key=True),
    )

    # ------------------------------------------------------------------
    # 12. pending_references (depends on claims, edge_types)
    # ------------------------------------------------------------------
    op.create_table(
        "pending_references",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("source_claim_id", sa.Uuid(), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("external_ref", sa.Text(), nullable=False),
        sa.Column("edge_type", sa.Text(), sa.ForeignKey("edge_types.name"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("resolved_to", sa.Uuid(), sa.ForeignKey("claims.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'resolved', 'expired')",
            name="ck_pending_references_status",
        ),
    )
    op.create_index(
        "idx_pending_refs_external",
        "pending_references",
        ["external_ref"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    # ------------------------------------------------------------------
    # Seed initial edge types (15 types from schema-proposal.md section 2)
    # ------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO edge_types (name, description, inverse_name, is_transitive, is_symmetric, category) VALUES
            -- Evidential
            ('supports',        'Source provides evidence for target',                    'supported_by',      false, false, 'evidential'),
            ('contradicts',     'Source provides evidence against target',                'contradicts',       false, true,  'evidential'),
            ('corroborates',    'Independent evidence for the same target',               'corroborated_by',   false, false, 'evidential'),
            -- Logical
            ('depends_on',      'Source requires target to hold',                         'depended_on_by',    true,  false, 'logical'),
            ('assumes',         'Source takes target as given without proof',             'assumed_by',        true,  false, 'logical'),
            ('derives_from',    'Source is logically derived from target',                'derives',           true,  false, 'logical'),
            ('implies',         'If source holds, target must hold',                      'implied_by',        true,  false, 'logical'),
            ('equivalent_to',   'Source and target are logically equivalent',             'equivalent_to',     true,  true,  'logical'),
            -- Structural
            ('generalizes',     'Source is a more general form of target',                'specializes',       true,  false, 'structural'),
            ('refines',         'Source is a more precise version of target',             'refined_by',        false, false, 'structural'),
            ('part_of',         'Source is a component of target',                        'has_part',          true,  false, 'structural'),
            ('instantiates',    'Source is a concrete instance of target pattern',        'instantiated_by',   false, false, 'structural'),
            -- Editorial
            ('supersedes',      'Source replaces target (versioning)',                    'superseded_by',     true,  false, 'editorial'),
            ('related_to',      'Weak/untyped association',                              'related_to',        false, true,  'editorial'),
            ('responds_to',     'Source is a response/reply to target',                  'responded_to_by',   false, false, 'editorial')
        """
    )

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------

    # Latest version of each claim lineage
    op.execute(
        """
        CREATE VIEW claims_latest AS
        SELECT DISTINCT ON (lineage_id) *
        FROM claims
        WHERE status IN ('active', 'draft')
        ORDER BY lineage_id, version DESC
        """
    )

    # Claims with aggregated review stats
    op.execute(
        """
        CREATE VIEW claims_with_confidence AS
        SELECT
            c.id,
            c.lineage_id,
            c.content,
            c.claim_type,
            c.status,
            c.version,
            COUNT(r.id) AS review_count,
            AVG(r.confidence) FILTER (WHERE r.verdict = 'endorse') AS avg_endorsement_confidence,
            COUNT(*) FILTER (WHERE r.verdict = 'endorse') AS endorsement_count,
            COUNT(*) FILTER (WHERE r.verdict = 'dispute') AS dispute_count,
            CASE
                WHEN COUNT(r.id) = 0 THEN 'unverified'
                WHEN COUNT(*) FILTER (WHERE r.verdict = 'dispute') > 0
                     AND COUNT(*) FILTER (WHERE r.verdict = 'endorse') > 0 THEN 'disputed'
                WHEN c.formal_content IS NOT NULL
                     AND COUNT(*) FILTER (WHERE r.verdict = 'endorse') > 0 THEN 'formally_verified'
                WHEN AVG(r.confidence) FILTER (WHERE r.verdict = 'endorse') > 0.7
                     AND COUNT(*) FILTER (WHERE r.verdict = 'endorse') > COUNT(*) FILTER (WHERE r.verdict = 'dispute')
                     THEN 'endorsed'
                ELSE 'under_review'
            END AS epistemic_status
        FROM claims c
        LEFT JOIN reviews r ON r.claim_id = c.id
        GROUP BY c.id
        """
    )


def downgrade() -> None:
    # Drop views first
    op.execute("DROP VIEW IF EXISTS claims_with_confidence")
    op.execute("DROP VIEW IF EXISTS claims_latest")

    # Drop tables in reverse dependency order
    op.drop_table("pending_references")
    op.drop_table("artifact_claims")
    op.drop_table("artifacts")
    op.drop_table("bundles")
    op.drop_table("reviews")
    op.drop_table("provenance")
    op.drop_table("edges")
    op.drop_table("edge_types")
    op.execute("DROP TABLE IF EXISTS claims")
    op.drop_table("sources")
    op.drop_table("namespaces")
    op.drop_table("agents")

    # Drop extensions
    op.execute('DROP EXTENSION IF EXISTS "vector"')
    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
