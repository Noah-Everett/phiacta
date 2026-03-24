# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""NEV-222: Add unique constraint on (from_entry_id, to_entry_id, rel) to entry_refs.

Prevents duplicate references between the same pair of entries with the
same relationship type.

Revision ID: 007
Revises: 006
Create Date: 2026-03-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: str | None = "006"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # Remove any pre-existing duplicate rows, keeping the earliest created_at
    op.execute(sa.text("""
        DELETE FROM entry_refs
        WHERE id NOT IN (
            SELECT DISTINCT ON (from_entry_id, to_entry_id, rel) id
            FROM entry_refs
            ORDER BY from_entry_id, to_entry_id, rel, created_at ASC
        )
    """))
    op.create_unique_constraint(
        "uq_entry_refs_from_to_rel",
        "entry_refs",
        ["from_entry_id", "to_entry_id", "rel"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_entry_refs_from_to_rel", "entry_refs", type_="unique")
