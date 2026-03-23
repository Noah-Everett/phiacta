# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""SQLAlchemy model for the extension_tags table.

Each row represents a single tag on a single entity, set by a specific user.
Tags are normalized to lowercase before insertion. The (entity_id, tag) pair
is unique — an entity cannot have the same tag twice.

Currently only entries can be tagged (enforced at the service layer).
The FK points to entities.id to support future entity types.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from phiacta.core.models.base import Base, UUIDMixin, _utcnow


class ExtensionTag(UUIDMixin, Base):
    __tablename__ = "extension_tags"

    entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    tag: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("entity_id", "tag", name="uq_extension_tags_entity_tag"),
        Index("ix_extension_tags_entity_id", "entity_id"),
        Index("ix_extension_tags_tag", "tag"),
    )
