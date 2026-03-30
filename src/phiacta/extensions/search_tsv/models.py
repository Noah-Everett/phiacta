# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""SQLAlchemy model for the view_search_tsv table.

Each row stores a precomputed tsvector for an entry at a specific view version.
The composite primary key (entry_id, version_id) supports blue-green version
swaps — both old and new versions can coexist during recomputation.

The tsv column uses PostgreSQL's TSVECTOR type (falls back to Text on SQLite
for test metadata creation).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy.types as types
from sqlalchemy import DateTime, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from phiacta.core.models.base import Base


class TSVector(types.TypeDecorator):
    """Platform-aware tsvector type.

    Uses PostgreSQL's native TSVECTOR on PostgreSQL; falls back to Text
    on other dialects (SQLite) so that Base.metadata.create_all works in
    test environments.
    """

    impl = types.Text
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[override]
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import TSVECTOR

            return dialect.type_descriptor(TSVECTOR())
        return dialect.type_descriptor(types.Text())


class ViewSearchTsv(Base):
    """Precomputed tsvector for full-text search.

    Composite PK (entry_id, version_id) — no surrogate UUID.
    GIN index on tsv for fast full-text search queries.
    ON DELETE CASCADE on both FKs ensures cleanup when entries or versions
    are removed.
    """

    __tablename__ = "view_search_tsv"

    entry_id: Mapped[UUID] = mapped_column(
        ForeignKey("entries.id", ondelete="CASCADE"), primary_key=True
    )
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("view_versions.id", ondelete="CASCADE"), primary_key=True
    )
    tsv: Mapped[str] = mapped_column(TSVector(), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_view_search_tsv_gin",
            "tsv",
            postgresql_using="gin",
        ),
    )
