# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from phiacta.models.base import Base

# Association table for artifact <-> claim many-to-many
artifact_claims = Table(
    "artifact_claims",
    Base.metadata,
    Column("artifact_id", ForeignKey("artifacts.id"), primary_key=True),
    Column("claim_id", ForeignKey("claims.id"), primary_key=True),
)


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    bundle_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("bundles.id"),
        default=None,
    )
    artifact_type: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    storage_ref: Mapped[str | None] = mapped_column(Text, default=None)
    content_inline: Mapped[str | None] = mapped_column(Text, default=None)
    structured_data: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        default=None,
    )
    attrs: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # Relationships
    claims: Mapped[list[Claim]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        secondary=artifact_claims,
        backref="artifacts",
    )
    bundle: Mapped[Bundle | None] = relationship()  # type: ignore[name-defined]  # noqa: F821
