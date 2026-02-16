# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from phiacta.models.base import Base, TimestampMixin, UUIDMixin


class Relation(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "relations"

    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id"),
        nullable=False,
    )
    target_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id"),
        nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(
        String,
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
        foreign_keys="[Relation.source_id]",
        back_populates="outgoing_relations",
    )
    target_claim: Mapped[Claim] = relationship(  # type: ignore[name-defined]  # noqa: F821
        foreign_keys="[Relation.target_id]",
        back_populates="incoming_relations",
    )
    asserted_by_agent: Mapped[Agent] = relationship(  # type: ignore[name-defined]  # noqa: F821
        foreign_keys="[Relation.created_by]",
    )

    __table_args__ = (
        UniqueConstraint("source_id", "target_id", "relation_type", "created_by"),
        CheckConstraint(
            "strength >= 0.0 AND strength <= 1.0",
            name="ck_relations_strength",
        ),
        Index("idx_relations_source", "source_id"),
        Index("idx_relations_target", "target_id"),
        Index("idx_relations_type", "relation_type"),
    )
