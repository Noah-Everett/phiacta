# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Activity model -- stub for entity registry feature.

All tests should FAIL against this stub until implementation is complete.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from phiacta.core.models.base import Base, UUIDMixin, _utcnow


class Activity(Base, UUIDMixin):
    __tablename__ = "activity"

    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("entities.id"), nullable=False,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("entities.id"), nullable=False,
    )
    activity_metadata: Mapped[dict | None] = mapped_column(
        "metadata", JSON, nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("idx_activity_actor", "actor_id", created_at.desc()),
        Index("idx_activity_entity", "entity_id", created_at.desc()),
    )
