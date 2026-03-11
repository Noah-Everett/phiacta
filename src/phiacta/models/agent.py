# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from sqlalchemy import Boolean, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from phiacta.models.base import Base, TimestampMixin, UUIDMixin


class Agent(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "agents"

    handle: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True
    )
    email: Mapped[str] = mapped_column(
        String(254), nullable=False, unique=True
    )
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )

    # Relationships
    created_entries: Mapped[list[Entry]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        foreign_keys="[Entry.created_by]",
        back_populates="created_by_agent",
    )

    __table_args__ = (
        Index("idx_agents_handle", "handle", unique=True),
        Index("idx_agents_email", "email", unique=True),
    )
