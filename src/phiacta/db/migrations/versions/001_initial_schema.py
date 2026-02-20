# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Initial schema: all tables, indexes, and constraints.

Revision ID: 001
Revises:
Create Date: 2026-02-20
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
    op.execute('CREATE EXTENSION IF NOT EXISTS "vector"')

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
        sa.Column("agent_type", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column(
            "trust_score",
            sa.Float(),
            nullable=False,
            server_default="1.0",
        ),
        sa.Column("api_key_hash", sa.Text(), nullable=True),
        sa.Column(
            "attrs",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="{}",
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
    op.create_index(
        "idx_agents_email_unique",
        "agents",
        ["email"],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )

    # ------------------------------------------------------------------
    # 2. namespaces
    # ------------------------------------------------------------------
    op.create_table(
        "namespaces",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "parent_id",
            sa.Uuid(),
            sa.ForeignKey("namespaces.id"),
            nullable=True,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "attrs",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="{}",
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
    op.create_index("idx_namespaces_parent", "namespaces", ["parent_id"])

    # ------------------------------------------------------------------
    # 3. sources
    # ------------------------------------------------------------------
    op.create_table(
        "sources",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("external_ref", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column(
            "submitted_by",
            sa.Uuid(),
            sa.ForeignKey("agents.id"),
            nullable=False,
        ),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "attrs",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
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
    # 4. claims (raw SQL for vector/tsvector column types)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE claims (
            id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            title           TEXT NOT NULL,
            claim_type      TEXT NOT NULL,
            format          VARCHAR DEFAULT 'markdown',
            content_cache   TEXT,
            namespace_id    UUID NOT NULL REFERENCES namespaces(id),
            created_by      UUID NOT NULL REFERENCES agents(id),
            status          VARCHAR NOT NULL DEFAULT 'active',
            forgejo_repo_id INTEGER,
            current_head_sha VARCHAR(40),
            repo_status     VARCHAR DEFAULT 'provisioning',
            search_tsv      TSVECTOR,
            embedding       vector(1536),
            attrs           JSONB NOT NULL DEFAULT '{}',
            cached_confidence DOUBLE PRECISION,
            confidence_updated_at TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_claims_status
                CHECK (status IN ('draft', 'active', 'archived', 'retracted')),
            CONSTRAINT ck_claims_repo_status
                CHECK (repo_status IN ('provisioning', 'ready', 'error'))
        )
        """
    )

    op.create_index("idx_claims_namespace", "claims", ["namespace_id"])
    op.create_index(
        "idx_claims_embedding",
        "claims",
        ["embedding"],
        postgresql_using="ivfflat",
        postgresql_with={"lists": 100},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "idx_claims_search_tsv",
        "claims",
        ["search_tsv"],
        postgresql_using="gin",
    )
    op.create_index(
        "idx_claims_attrs",
        "claims",
        ["attrs"],
        postgresql_using="gin",
    )
    op.create_index(
        "idx_claims_active",
        "claims",
        ["status"],
        postgresql_where=sa.text("status = 'active'"),
    )

    # ------------------------------------------------------------------
    # 5. interactions
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
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("signal", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "weight",
            sa.Float(),
            nullable=False,
            server_default="1.0",
        ),
        sa.Column("author_trust_snapshot", sa.Float(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("origin_uri", sa.Text(), nullable=True),
        sa.Column(
            "attrs",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.CheckConstraint(
            "kind IN ('vote', 'review')",
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
            "kind != 'review' OR body IS NOT NULL",
            name="ck_interactions_body_required",
        ),
    )
    op.create_index("idx_interactions_claim", "interactions", ["claim_id"])
    op.create_index("idx_interactions_author", "interactions", ["author_id"])
    op.create_index(
        "idx_interactions_claim_signal",
        "interactions",
        ["claim_id", "signal", "confidence"],
        postgresql_where=sa.text(
            "signal IS NOT NULL AND deleted_at IS NULL"
        ),
    )
    op.create_index(
        "idx_interactions_claim_kind",
        "interactions",
        ["claim_id", "kind"],
    )
    op.create_index(
        "uq_interactions_claim_author_signal",
        "interactions",
        ["claim_id", "author_id"],
        unique=True,
        postgresql_where=sa.text(
            "signal IS NOT NULL AND deleted_at IS NULL"
        ),
    )

    # ------------------------------------------------------------------
    # 6. references
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
        sa.Column(
            "source_claim_id",
            sa.Uuid(),
            sa.ForeignKey("claims.id"),
            nullable=True,
        ),
        sa.Column(
            "target_claim_id",
            sa.Uuid(),
            sa.ForeignKey("claims.id"),
            nullable=True,
        ),
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
    op.create_index(
        "uq_references_source_target_role",
        "references",
        ["source_uri", "target_uri", "role"],
        unique=True,
    )

    # ------------------------------------------------------------------
    # 7. outbox
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
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            nullable=False,
            server_default="5",
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
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
    # 8. bundles
    # ------------------------------------------------------------------
    op.create_table(
        "bundles",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "submitted_by",
            sa.Uuid(),
            sa.ForeignKey("agents.id"),
            nullable=False,
        ),
        sa.Column("extension_id", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="accepted",
        ),
        sa.Column(
            "claim_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "reference_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "artifact_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "attrs",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.CheckConstraint(
            "status IN ('accepted', 'rejected', 'processing')",
            name="ck_bundles_status",
        ),
    )

    # ------------------------------------------------------------------
    # 9. artifacts
    # ------------------------------------------------------------------
    op.create_table(
        "artifacts",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "bundle_id",
            sa.Uuid(),
            sa.ForeignKey("bundles.id"),
            nullable=True,
        ),
        sa.Column("artifact_type", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("storage_ref", sa.Text(), nullable=True),
        sa.Column("content_inline", sa.Text(), nullable=True),
        sa.Column(
            "structured_data",
            sa.dialects.postgresql.JSONB(),
            nullable=True,
        ),
        sa.Column(
            "attrs",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ------------------------------------------------------------------
    # 10. artifact_claims
    # ------------------------------------------------------------------
    op.create_table(
        "artifact_claims",
        sa.Column(
            "artifact_id",
            sa.Uuid(),
            sa.ForeignKey("artifacts.id"),
            primary_key=True,
        ),
        sa.Column(
            "claim_id",
            sa.Uuid(),
            sa.ForeignKey("claims.id"),
            primary_key=True,
        ),
    )

    # ------------------------------------------------------------------
    # 11. extensions
    # ------------------------------------------------------------------
    op.create_table(
        "extensions",
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
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("extension_type", sa.String(32), nullable=False),
        sa.Column("base_url", sa.String(2048), nullable=False),
        sa.Column("description", sa.String(1024), nullable=True),
        sa.Column(
            "registered_by",
            sa.Uuid(),
            sa.ForeignKey("agents.id"),
            nullable=False,
        ),
        sa.Column(
            "health_status",
            sa.String(16),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "last_heartbeat",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "manifest",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "subscribed_events",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.CheckConstraint(
            "extension_type IN ('ingestion', 'analysis', 'integration')",
            name="ck_extensions_type",
        ),
        sa.CheckConstraint(
            "health_status IN ('healthy', 'unhealthy', 'unknown')",
            name="ck_extensions_health_status",
        ),
    )
    op.create_index(
        "idx_extensions_name_version",
        "extensions",
        ["name", "version"],
        unique=True,
    )
    op.create_index(
        "idx_extensions_type",
        "extensions",
        ["extension_type"],
    )
    op.create_index(
        "idx_extensions_healthy",
        "extensions",
        ["health_status"],
        postgresql_where=sa.text("health_status = 'healthy'"),
    )

    # ------------------------------------------------------------------
    # 12. layers
    # ------------------------------------------------------------------
    op.create_table(
        "layers",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "config",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="{}",
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


def downgrade() -> None:
    op.drop_table("layers")
    op.drop_table("extensions")
    op.drop_table("artifact_claims")
    op.drop_table("artifacts")
    op.drop_table("bundles")
    op.drop_table("outbox")
    op.drop_table("references")
    op.drop_table("interactions")
    op.drop_table("claims")
    op.drop_table("sources")
    op.drop_table("namespaces")
    op.drop_table("agents")
    op.execute('DROP EXTENSION IF EXISTS "vector"')
    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
