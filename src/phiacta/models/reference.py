# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

import enum
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from phiacta.models.base import Base, TimestampMixin, UUIDMixin


class ReferenceRole(str, enum.Enum):
    EVIDENCE = "evidence"
    REBUTS = "rebuts"
    RELATED = "related"
    FIXES = "fixes"
    DERIVES_FROM = "derives_from"
    SUPERSEDES = "supersedes"
    CITATION = "citation"
    CORROBORATION = "corroboration"
    METHOD = "method"


class Reference(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "references"

    source_uri: Mapped[str] = mapped_column(String, nullable=False)
    target_uri: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[ReferenceRole] = mapped_column(String, nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id"), nullable=False
    )

    # Denormalized for query performance (computed on insert, immutable)
    source_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source_claim_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("claims.id"), nullable=True, index=True
    )
    target_claim_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("claims.id"), nullable=True, index=True
    )

    __table_args__ = (
        Index("idx_references_source_uri", "source_uri"),
        Index("idx_references_target_uri", "target_uri"),
        Index("idx_references_source_claim", "source_claim_id"),
        Index("idx_references_target_claim", "target_claim_id"),
        Index(
            "uq_references_source_target_role",
            "source_uri", "target_uri", "role",
            unique=True,
        ),
    )
