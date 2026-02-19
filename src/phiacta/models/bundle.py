# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from phiacta.models.base import Base, UUIDMixin


class Bundle(UUIDMixin, Base):
    __tablename__ = "bundles"

    idempotency_key: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        unique=True,
    )
    submitted_by: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id"),
        nullable=False,
    )
    extension_id: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    status: Mapped[str] = mapped_column(String, default="accepted")
    claim_count: Mapped[int] = mapped_column(Integer, default=0)
    reference_count: Mapped[int] = mapped_column(Integer, default=0)
    artifact_count: Mapped[int] = mapped_column(Integer, default=0)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    attrs: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="{}",
    )

    # Relationships
    submitter: Mapped[Agent] = relationship(  # type: ignore[name-defined]  # noqa: F821
        foreign_keys="[Bundle.submitted_by]",
    )
    artifacts: Mapped[list[Artifact]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="bundle",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('accepted', 'rejected', 'processing')",
            name="ck_bundles_status",
        ),
    )
