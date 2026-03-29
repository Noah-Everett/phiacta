# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Graph tool schemas."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class GraphRef(BaseModel):
    """A single reference within a grouped edge."""

    id: UUID
    rel: str
    direction: str  # "forward" or "reverse" relative to source→target
    note: str | None = None
    weight: float | None = None


class GraphEdge(BaseModel):
    """A grouped edge between two nodes (unordered pair)."""

    source: UUID
    target: UUID
    refs: list[GraphRef]


class GraphNode(BaseModel):
    """A node in the graph (an entry)."""

    id: UUID
    title: str | None = None
    summary: str | None = None
    entry_type: str | None = None
    tags: list[str] = []
    visibility: str = "public"
    depth: int


class GraphResponse(BaseModel):
    """Full graph response."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool
    seed_ids: list[UUID]
    mode: str
