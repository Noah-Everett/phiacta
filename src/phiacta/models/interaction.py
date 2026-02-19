# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from phiacta.models.base import Base, TimestampMixin, UUIDMixin


class Interaction(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "interactions"

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"),
        nullable=False,
    )
    author_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id"),
        nullable=False,
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("interactions.id"),
        default=None,
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    signal: Mapped[str | None] = mapped_column(String, default=None)
    confidence: Mapped[float | None] = mapped_column(Float, default=None)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    author_trust_snapshot: Mapped[float | None] = mapped_column(
        Float, default=None
    )
    body: Mapped[str | None] = mapped_column(Text, default=None)
    origin_uri: Mapped[str | None] = mapped_column(Text, default=None)
    attrs: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="{}",
    )

    # Relationships
    claim: Mapped[Claim] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="interactions",
    )
    author: Mapped[Agent] = relationship(  # type: ignore[name-defined]  # noqa: F821
        foreign_keys="[Interaction.author_id]",
    )
    parent: Mapped[Interaction | None] = relationship(
        remote_side="[Interaction.id]",
        back_populates="replies",
    )
    replies: Mapped[list[Interaction]] = relationship(
        back_populates="parent",
    )
    references: Mapped[list[InteractionReference]] = relationship(
        back_populates="interaction",
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('comment', 'vote', 'review', 'issue', 'suggestion')",
            name="ck_interactions_kind",
        ),
        CheckConstraint(
            "signal IS NULL OR signal IN ('agree', 'disagree', 'neutral')",
            name="ck_interactions_signal",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)",
            name="ck_interactions_confidence",
        ),
        CheckConstraint(
            "(signal IS NULL AND confidence IS NULL)"
            " OR (signal IS NOT NULL AND confidence IS NOT NULL)",
            name="ck_interactions_signal_confidence",
        ),
        CheckConstraint(
            "kind != 'vote' OR signal IS NOT NULL",
            name="ck_interactions_vote_signal",
        ),
        CheckConstraint(
            "kind NOT IN ('comment', 'review', 'issue', 'suggestion')"
            " OR body IS NOT NULL",
            name="ck_interactions_body_required",
        ),
        Index("idx_interactions_claim", "claim_id"),
        Index(
            "idx_interactions_parent",
            "parent_id",
            postgresql_where=text("parent_id IS NOT NULL"),
        ),
        Index("idx_interactions_author", "author_id"),
        Index(
            "idx_interactions_claim_signal",
            "claim_id",
            "signal",
            "confidence",
            postgresql_where=text(
                "signal IS NOT NULL AND deleted_at IS NULL"
            ),
        ),
        Index("idx_interactions_claim_kind", "claim_id", "kind"),
        Index("idx_interactions_attrs", "attrs", postgresql_using="gin"),
        Index(
            "uq_interactions_claim_author_signal",
            "claim_id",
            "author_id",
            unique=True,
            postgresql_where=text(
                "signal IS NOT NULL AND deleted_at IS NULL"
            ),
        ),
    )


class InteractionReference(Base):
    __tablename__ = "interaction_references"

    interaction_id: Mapped[UUID] = mapped_column(
        ForeignKey("interactions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    ref_type: Mapped[str] = mapped_column(String, primary_key=True)
    ref_id: Mapped[UUID] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String, nullable=False)
    attrs: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="{}",
    )

    # Relationships
    interaction: Mapped[Interaction] = relationship(
        back_populates="references",
    )

    __table_args__ = (
        CheckConstraint(
            "ref_type IN ('claim', 'source', 'artifact')",
            name="ck_interaction_references_ref_type",
        ),
        CheckConstraint(
            "role IN ('evidence', 'citation', 'rebuttal', 'context',"
            " 'method', 'corroboration', 'dataset')",
            name="ck_interaction_references_role",
        ),
        Index("idx_interaction_references_ref", "ref_type", "ref_id"),
    )
