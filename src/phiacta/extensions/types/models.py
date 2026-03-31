# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""SQLAlchemy model for the extension_types table."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from phiacta.core.models.base import Base, UUIDMixin, _utcnow


class ExtensionType(UUIDMixin, Base):
    __tablename__ = "extension_types"

    entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    entry_type: Mapped[str] = mapped_column(String(100), nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(),
        onupdate=_utcnow,
    )

    __table_args__ = (
        UniqueConstraint("entity_id", name="uq_extension_types_entity"),
        Index("ix_extension_types_entity_id", "entity_id"),
        Index("ix_extension_types_entry_type", "entry_type"),
    )
