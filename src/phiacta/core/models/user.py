# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from phiacta.core.models.base import Base, TimestampMixin, UUIDMixin


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"

    handle: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True
    )
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    # Relationships
    created_entries: Mapped[list[Entry]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        foreign_keys="[Entry.created_by]",
        back_populates="created_by_user",
    )

    __table_args__ = (
        Index("idx_users_handle", "handle", unique=True),
    )
