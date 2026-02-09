# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NewPublishing Contributors

from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, Float, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newpublishing.models.base import Base, TimestampMixin, UUIDMixin


class Agent(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "agents"

    agent_type: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str | None] = mapped_column(Text, default=None)
    trust_score: Mapped[float] = mapped_column(Float, default=1.0)
    api_key_hash: Mapped[str | None] = mapped_column(Text, default=None)
    attrs: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="{}",
    )

    # Relationships
    created_claims: Mapped[list[Claim]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        foreign_keys="[Claim.created_by]",
        back_populates="created_by_agent",
    )

    __table_args__ = (
        CheckConstraint(
            "agent_type IN ('human', 'ai', 'organization', 'pipeline', 'extension')",
            name="ck_agents_agent_type",
        ),
        Index(
            "idx_agents_external_id",
            "external_id",
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )
