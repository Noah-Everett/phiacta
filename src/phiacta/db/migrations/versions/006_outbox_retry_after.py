# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Add retry_after column to outbox for exponential backoff.
Backfill outbox entries for orphaned claims from pre-git-backed era.

Revision ID: 006
Revises: 005
Create Date: 2026-02-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: str = "005"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "outbox",
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
    )

    # Reset any stuck entries so the new retry logic picks them up
    op.execute(
        "UPDATE outbox SET status = 'pending', attempts = 0, retry_after = NULL "
        "WHERE status IN ('failed', 'processing')"
    )

    # Backfill outbox entries for claims created before the git-backed migration.
    # Migration 004 set repo_status='provisioning' on all existing claims but
    # did not create corresponding outbox entries to provision their repos.
    op.execute(
        """
        INSERT INTO outbox (id, operation, payload, status)
        SELECT
            uuid_generate_v4(),
            'create_repo',
            jsonb_build_object(
                'claim_id', c.id::text,
                'title', c.title,
                'content', COALESCE(c.content_cache, ''),
                'format', COALESCE(c.format, 'markdown'),
                'author_id', COALESCE(c.created_by::text, 'service'),
                'author_name', 'phiacta-service'
            ),
            'pending'
        FROM claims c
        WHERE c.repo_status = 'provisioning'
          AND c.forgejo_repo_id IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM outbox o
              WHERE o.payload->>'claim_id' = c.id::text
                AND o.operation = 'create_repo'
          )
        """
    )


def downgrade() -> None:
    op.drop_column("outbox", "retry_after")
