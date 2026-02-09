# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NewPublishing Contributors

from __future__ import annotations

from uuid import UUID

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newpublishing.models.base import Base, TimestampMixin, UUIDMixin


class Namespace(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "namespaces"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("namespaces.id"),
        default=None,
    )
    description: Mapped[str | None] = mapped_column(Text, default=None)
    attrs: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="{}",
    )

    # Relationships
    parent: Mapped[Namespace | None] = relationship(
        remote_side="[Namespace.id]",
        back_populates="children",
    )
    children: Mapped[list[Namespace]] = relationship(
        back_populates="parent",
    )
    claims: Mapped[list[Claim]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="namespace",
    )

    __table_args__ = (Index("idx_namespaces_parent", "parent_id"),)
