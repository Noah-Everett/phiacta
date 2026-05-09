# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Add indexes on jobs.submitted_by and jobs.entity_id for list queries.

Revision ID: 019
Revises: 018
"""

from alembic import op

revision: str = "019"
down_revision: str | None = "018"
branch_labels: tuple | None = None
depends_on: tuple | None = None


def upgrade() -> None:
    op.create_index("ix_jobs_submitted_by", "jobs", ["submitted_by"])
    op.execute(
        "CREATE INDEX ix_jobs_entity_id ON jobs (entity_id) WHERE entity_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_entity_id", table_name="jobs")
    op.drop_index("ix_jobs_submitted_by", table_name="jobs")
