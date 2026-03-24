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
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from phiacta.core.models.base import Base, UUIDMixin


class EntryRef(UUIDMixin, Base):
    __tablename__ = "entry_refs"

    from_entry_id: Mapped[UUID] = mapped_column(
        ForeignKey("entries.id"), nullable=False
    )
    to_entry_id: Mapped[UUID] = mapped_column(
        ForeignKey("entries.id"), nullable=False
    )
    rel: Mapped[str] = mapped_column(String(50), nullable=False)
    version_sha: Mapped[str | None] = mapped_column(String(40), default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "from_entry_id != to_entry_id",
            name="ck_entry_refs_no_self_ref",
        ),
        UniqueConstraint(
            "from_entry_id", "to_entry_id", "rel",
            name="uq_entry_refs_from_to_rel",
        ),
        Index("ix_entry_refs_from", "from_entry_id"),
        Index("ix_entry_refs_to", "to_entry_id"),
        Index("ix_entry_refs_rel", "rel"),
    )
