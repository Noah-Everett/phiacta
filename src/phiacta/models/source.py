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
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from phiacta.models.base import Base, UUIDMixin


class Source(UUIDMixin, Base):
    __tablename__ = "sources"

    source_type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, default=None)
    external_ref: Mapped[str | None] = mapped_column(Text, default=None)
    content_hash: Mapped[str | None] = mapped_column(Text, default=None)
    submitted_by: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id"),
        nullable=False,
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    attrs: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="{}",
    )

    # Relationships
    submitter: Mapped[Agent] = relationship(  # type: ignore[name-defined]  # noqa: F821
        foreign_keys="[Source.submitted_by]",
    )

    __table_args__ = (
        CheckConstraint(
            "source_type IN ("
            "'paper', 'preprint', 'recording', 'photo', 'conversation', "
            "'code', 'dataset', 'url', 'manual_entry')",
            name="ck_sources_source_type",
        ),
        Index(
            "idx_sources_external_ref",
            "external_ref",
            postgresql_where=text("external_ref IS NOT NULL"),
        ),
        Index(
            "idx_sources_content_hash",
            "content_hash",
            postgresql_where=text("content_hash IS NOT NULL"),
        ),
    )
