# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NewPublishing Contributors

from __future__ import annotations

from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newpublishing.models.base import Base, TimestampMixin, UUIDMixin


class EdgeType(Base):
    __tablename__ = "edge_types"

    name: Mapped[str] = mapped_column(String, primary_key=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    inverse_name: Mapped[str | None] = mapped_column(String, default=None)
    is_transitive: Mapped[bool] = mapped_column(Boolean, default=False)
    is_symmetric: Mapped[bool] = mapped_column(Boolean, default=False)
    category: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "category IN ('evidential', 'logical', 'structural', 'editorial')",
            name="ck_edge_types_category",
        ),
    )


class Edge(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "edges"

    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id"),
        nullable=False,
    )
    target_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id"),
        nullable=False,
    )
    edge_type: Mapped[str] = mapped_column(
        ForeignKey("edge_types.name"),
        nullable=False,
    )
    strength: Mapped[float | None] = mapped_column(Float, default=None)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id"),
        nullable=False,
    )
    source_provenance: Mapped[UUID | None] = mapped_column(
        ForeignKey("sources.id"),
        default=None,
    )
    attrs: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="{}",
    )

    # Relationships
    source_claim: Mapped[Claim] = relationship(  # type: ignore[name-defined]  # noqa: F821
        foreign_keys="[Edge.source_id]",
        back_populates="outgoing_edges",
    )
    target_claim: Mapped[Claim] = relationship(  # type: ignore[name-defined]  # noqa: F821
        foreign_keys="[Edge.target_id]",
        back_populates="incoming_edges",
    )
    edge_type_rel: Mapped[EdgeType] = relationship()
    asserted_by_agent: Mapped[Agent] = relationship(  # type: ignore[name-defined]  # noqa: F821
        foreign_keys="[Edge.created_by]",
    )

    __table_args__ = (
        UniqueConstraint("source_id", "target_id", "edge_type", "created_by"),
        CheckConstraint(
            "strength >= 0.0 AND strength <= 1.0",
            name="ck_edges_strength",
        ),
        Index("idx_edges_source", "source_id"),
        Index("idx_edges_target", "target_id"),
        Index("idx_edges_type", "edge_type"),
    )
