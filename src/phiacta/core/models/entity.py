# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Entity model -- stub for entity registry feature.

All tests should FAIL against this stub until implementation is complete.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from phiacta.core.models.base import Base, UUIDMixin, _utcnow


class Entity(Base, UUIDMixin):
    __tablename__ = "entities"

    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("entities.id", ondelete="SET NULL"), nullable=True,
    )
    external_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("entities.id", ondelete="SET NULL"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("idx_entities_type", "entity_type"),
        Index("idx_entities_parent", "parent_id"),
        Index("idx_entities_created_by", "created_by"),
        Index(
            "idx_entities_parent_ref",
            "parent_id",
            "external_ref",
            unique=True,
            sqlite_where=external_ref.isnot(None),
            postgresql_where=external_ref.isnot(None),
        ),
    )
