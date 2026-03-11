# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from phiacta.models.base import Base, TimestampMixin, UUIDMixin


class Entry(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "entries"

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    layout_hint: Mapped[str | None] = mapped_column(String(50), default=None)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    license: Mapped[str | None] = mapped_column(String(50), default=None)
    content_format: Mapped[str] = mapped_column(
        String(20), nullable=False, default="markdown"
    )
    content_cache: Mapped[str | None] = mapped_column(Text, default=None)
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )

    # Git sync
    forgejo_repo_id: Mapped[int | None] = mapped_column(Integer, default=None)
    repo_name: Mapped[str] = mapped_column(String(200), nullable=False)
    current_head_sha: Mapped[str | None] = mapped_column(
        String(40), default=None
    )
    repo_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="provisioning"
    )

    # Status
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"
    )

    # Creator
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id"), nullable=False
    )

    # Relationships
    created_by_agent: Mapped[Agent] = relationship(  # type: ignore[name-defined]  # noqa: F821
        foreign_keys="[Entry.created_by]",
    )

    __table_args__ = (
        Index(
            "idx_entries_active",
            "status",
            postgresql_where=text("status = 'active'"),
        ),
        Index("idx_entries_layout_hint", "layout_hint"),
        Index("idx_entries_created_by", "created_by"),
    )
