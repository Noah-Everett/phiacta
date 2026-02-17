# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from phiacta.models.base import Base, TimestampMixin, UUIDMixin


class Extension(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "extensions"

    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    extension_type: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), default=None)
    registered_by: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id"), nullable=False
    )
    health_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unknown"
    )
    last_heartbeat: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    manifest: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    subscribed_events: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )

    __table_args__ = (
        CheckConstraint(
            "extension_type IN ('ingestion', 'analysis', 'integration')",
            name="ck_extensions_type",
        ),
        CheckConstraint(
            "health_status IN ('healthy', 'unhealthy', 'unknown')",
            name="ck_extensions_health_status",
        ),
        UniqueConstraint("name", name="uq_extensions_name"),
        Index("idx_extensions_name_version", "name", "version", unique=True),
        Index(
            "idx_extensions_type",
            "extension_type",
        ),
        Index(
            "idx_extensions_healthy",
            "health_status",
            postgresql_where=text("health_status = 'healthy'"),
        ),
    )
