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
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from phiacta.models.base import Base, TimestampMixin, UUIDMixin


class Review(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "reviews"

    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id"),
        nullable=False,
    )
    reviewer_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id"),
        nullable=False,
    )
    verdict: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, default=None)

    # Relationships
    claim: Mapped[Claim] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="reviews",
    )
    reviewer: Mapped[Agent] = relationship(  # type: ignore[name-defined]  # noqa: F821
        foreign_keys="[Review.reviewer_id]",
    )

    __table_args__ = (
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_reviews_confidence",
        ),
        UniqueConstraint("claim_id", "reviewer_id"),
        Index("idx_reviews_claim", "claim_id"),
        Index("idx_reviews_reviewer", "reviewer_id"),
    )
