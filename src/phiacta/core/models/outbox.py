# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from phiacta.core.models.base import Base, UUIDMixin


class Outbox(UUIDMixin, Base):
    __tablename__ = "outbox"

    aggregate_id: Mapped[UUID] = mapped_column(nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(30), nullable=False)
    operation: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, server_default="{}"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default=text("'pending'"),
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"),
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    process_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_outbox_poll",
            "status",
            "process_after",
            postgresql_where=text("status = 'pending'"),
        ),
    )
