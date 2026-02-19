# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Review fixes: rename relation_count, add reference FKs and unique constraint,
create extensions table.

Revision ID: 005
Revises: 004
Create Date: 2026-02-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: str = "004"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Rename bundles.relation_count → reference_count
    # ------------------------------------------------------------------
    op.alter_column(
        "bundles",
        "relation_count",
        new_column_name="reference_count",
    )

    # ------------------------------------------------------------------
    # 2. Add FK constraints on references.source_claim_id / target_claim_id
    # ------------------------------------------------------------------
    op.create_foreign_key(
        "fk_references_source_claim",
        "references",
        "claims",
        ["source_claim_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_references_target_claim",
        "references",
        "claims",
        ["target_claim_id"],
        ["id"],
    )

    # ------------------------------------------------------------------
    # 3. Add unique constraint on (source_uri, target_uri, role)
    # ------------------------------------------------------------------
    op.create_index(
        "uq_references_source_target_role",
        "references",
        ["source_uri", "target_uri", "role"],
        unique=True,
    )

    # ------------------------------------------------------------------
    # 4. Create extensions table
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
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("extension_type", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "health_status",
            sa.String(),
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
        sa.Column(
            "registered_by",
            sa.Uuid(),
            sa.ForeignKey("agents.id"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "health_status IN ('healthy', 'unhealthy', 'unknown')",
            name="ck_extensions_health_status",
        ),
    )
    op.create_index(
        "idx_extensions_registered_by", "extensions", ["registered_by"]
    )
    op.create_index(
        "idx_extensions_type", "extensions", ["extension_type"]
    )
    op.create_index(
        "idx_extensions_subscribed_events",
        "extensions",
        ["subscribed_events"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    # Drop extensions table
    op.drop_table("extensions")

    # Drop unique constraint on references
    op.drop_index("uq_references_source_target_role", table_name="references")

    # Drop FK constraints on references
    op.drop_constraint(
        "fk_references_target_claim", "references", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_references_source_claim", "references", type_="foreignkey"
    )

    # Rename back
    op.alter_column(
        "bundles",
        "reference_count",
        new_column_name="relation_count",
    )
