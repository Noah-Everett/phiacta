# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NewPublishing Contributors

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from newpublishing.models.base import Base, UUIDMixin


class PendingReference(UUIDMixin, Base):
    __tablename__ = "pending_references"

    source_claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id"),
        nullable=False,
    )
    external_ref: Mapped[str] = mapped_column(Text, nullable=False)
    relation_type: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String, default="pending")
    resolved_to: Mapped[UUID | None] = mapped_column(
        ForeignKey("claims.id"),
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'resolved', 'expired')",
            name="ck_pending_references_status",
        ),
        Index(
            "idx_pending_refs_external",
            "external_ref",
            postgresql_where=text("status = 'pending'"),
        ),
    )
