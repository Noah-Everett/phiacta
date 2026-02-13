# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NewPublishing Contributors

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from newpublishing.models.base import Base


class GraphEdgeType(Base):
    """Edge type registry owned by the graph layer.

    Defines semantic properties (transitivity, symmetry) for relation types
    that the graph layer understands. Stored in its own table, not in core.
    """

    __tablename__ = "graph_edge_types"

    name: Mapped[str] = mapped_column(String, primary_key=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    inverse_name: Mapped[str | None] = mapped_column(String, default=None)
    is_transitive: Mapped[bool] = mapped_column(Boolean, default=False)
    is_symmetric: Mapped[bool] = mapped_column(Boolean, default=False)
    category: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "category IN ('evidential', 'logical', 'structural', 'editorial')",
            name="ck_graph_edge_types_category",
        ),
    )
