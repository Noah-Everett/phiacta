# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""SQLAlchemy model for the extension_references table."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from phiacta.core.models.base import Base, UUIDMixin, _utcnow


class ExtensionReference(UUIDMixin, Base):
    __tablename__ = "extension_references"

    from_entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    to_entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    rel: Mapped[str] = mapped_column(String(50), nullable=False)
    version_sha: Mapped[str | None] = mapped_column(String(40), default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("from_entity_id != to_entity_id", name="ck_extension_references_no_self_ref"),
        UniqueConstraint("from_entity_id", "to_entity_id", "rel", name="uq_extension_references_from_to_rel"),
        Index("ix_extension_references_from", "from_entity_id"),
        Index("ix_extension_references_to", "to_entity_id"),
        Index("ix_extension_references_rel", "rel"),
    )
