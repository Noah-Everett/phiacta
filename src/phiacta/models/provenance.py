# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from phiacta.models.base import Base, UUIDMixin


class Provenance(UUIDMixin, Base):
    __tablename__ = "provenance"

    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id"),
        nullable=False,
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("sources.id"),
        nullable=False,
    )
    extracted_by: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id"),
        nullable=False,
    )
    extraction_method: Mapped[str | None] = mapped_column(String, default=None)
    location_in_source: Mapped[str | None] = mapped_column(Text, default=None)
    confidence: Mapped[float | None] = mapped_column(Float, default=None)
    attrs: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="{}",
    )
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # Relationships
    claim: Mapped[Claim] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="provenance_records",
    )
    source: Mapped[Source] = relationship(  # type: ignore[name-defined]  # noqa: F821
        foreign_keys="[Provenance.source_id]",
    )
    extractor: Mapped[Agent] = relationship(  # type: ignore[name-defined]  # noqa: F821
        foreign_keys="[Provenance.extracted_by]",
    )

    __table_args__ = (
        UniqueConstraint("claim_id", "source_id", "extracted_by"),
        Index("idx_provenance_claim", "claim_id"),
        Index("idx_provenance_source", "source_id"),
    )
