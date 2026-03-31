# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Add UNIQUE constraint on entries.repo_name.

Revision ID: 013
Revises: 012
"""

from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_entries_repo_name", "entries", ["repo_name"])


def downgrade() -> None:
    op.drop_constraint("uq_entries_repo_name", "entries", type_="unique")
