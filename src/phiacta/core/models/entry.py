# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from phiacta.core.models.base import Base, TimestampMixin, UUIDMixin


class Entry(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "entries"

    # Git sync
    forgejo_repo_id: Mapped[int | None] = mapped_column(Integer, default=None)
    repo_name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    current_head_sha: Mapped[str | None] = mapped_column(
        String(40), default=None
    )
    repo_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="provisioning"
    )

    # Visibility — controls who can see the entry
    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, default="public"
    )

    # Creator
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    # Relationships
    created_by_user: Mapped[User] = relationship(  # type: ignore[name-defined]  # noqa: F821
        foreign_keys="[Entry.created_by]",
        lazy="raise",
    )

    __table_args__ = (
        Index(
            "idx_entries_public",
            "visibility",
            postgresql_where=text("visibility = 'public'"),
        ),
        Index("idx_entries_created_by", "created_by"),
    )
