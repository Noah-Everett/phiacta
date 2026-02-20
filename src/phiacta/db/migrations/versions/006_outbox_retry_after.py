# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Add retry_after column to outbox for exponential backoff.

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


def downgrade() -> None:
    op.drop_column("outbox", "retry_after")
