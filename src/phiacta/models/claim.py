# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from phiacta.models.base import Base, TimestampMixin, UUIDMixin


class Claim(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "claims"

    lineage_id: Mapped[UUID] = mapped_column(index=False)
    version: Mapped[int] = mapped_column(default=1)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    namespace_id: Mapped[UUID] = mapped_column(
        ForeignKey("namespaces.id"),
        nullable=False,
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id"),
        nullable=False,
    )
    formal_content: Mapped[str | None] = mapped_column(Text, default=None)
    supersedes: Mapped[UUID | None] = mapped_column(
        ForeignKey("claims.id"),
        default=None,
    )
    status: Mapped[str] = mapped_column(
        String,
        default="active",
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1536),
        default=None,
    )
    search_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        default=None,
    )
    attrs: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="{}",
    )

    # Relationships (use string references for cross-model forward refs)
    namespace: Mapped[Namespace] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="claims",
    )
    outgoing_relations: Mapped[list[Relation]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        foreign_keys="[Relation.source_id]",
        back_populates="source_claim",
    )
    incoming_relations: Mapped[list[Relation]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        foreign_keys="[Relation.target_id]",
        back_populates="target_claim",
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
        UniqueConstraint("lineage_id", "version"),
        CheckConstraint(
            "status IN ('draft', 'active', 'deprecated', 'retracted')",
            name="ck_claims_status",
        ),
        Index("idx_claims_lineage", "lineage_id", "version", postgresql_using="btree"),
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
