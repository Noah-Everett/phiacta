# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from phiacta.models.base import Base, TimestampMixin, UUIDMixin


class Claim(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "claims"

    # Content metadata (denormalized from claim.yaml for queryability)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str] = mapped_column(String, nullable=False)
    format: Mapped[str] = mapped_column(String, default="markdown")
    content_cache: Mapped[str | None] = mapped_column(Text, default=None)

    # Organization
    namespace_id: Mapped[UUID] = mapped_column(
        ForeignKey("namespaces.id"),
        nullable=False,
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id"),
        nullable=False,
    )

    # Status (note: old "deprecated" renamed to "archived")
    status: Mapped[str] = mapped_column(String, default="active")

    # Git sync
    forgejo_repo_id: Mapped[int | None] = mapped_column(Integer, default=None)
    current_head_sha: Mapped[str | None] = mapped_column(
        String(40), default=None
    )
    repo_status: Mapped[str] = mapped_column(String, default="provisioning")

    # Search
    search_tsv: Mapped[str | None] = mapped_column(TSVECTOR, default=None)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1536), default=None
    )

    # Extensible metadata
    attrs: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # Cached confidence (refreshed on vote/review changes)
    cached_confidence: Mapped[float | None] = mapped_column(
        Float, default=None
    )
    confidence_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    # Relationships
    namespace: Mapped[Namespace] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="claims",
    )
    provenance_records: Mapped[list[Provenance]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="claim",
    )
    interactions: Mapped[list[Interaction]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="claim",
    )
    created_by_agent: Mapped[Agent] = relationship(  # type: ignore[name-defined]  # noqa: F821
        foreign_keys="[Claim.created_by]",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'archived', 'retracted')",
            name="ck_claims_status",
        ),
        CheckConstraint(
            "repo_status IN ('provisioning', 'ready', 'error')",
            name="ck_claims_repo_status",
        ),
        Index("idx_claims_namespace", "namespace_id"),
        Index(
            "idx_claims_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("idx_claims_search_tsv", "search_tsv", postgresql_using="gin"),
        Index("idx_claims_attrs", "attrs", postgresql_using="gin"),
        Index(
            "idx_claims_active",
            "status",
            postgresql_where=text("status = 'active'"),
        ),
    )
