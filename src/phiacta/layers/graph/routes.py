# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from collections import deque
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.db.session import get_db
from phiacta.layers.graph.models import GraphEdgeType
from phiacta.models.relation import Relation


class TraverseRequest(BaseModel):
    start_id: UUID
    max_depth: int = 3
    relation_types: list[str] | None = None
    direction: str = "both"
    algorithm: str = "bfs"


class TraverseNode(BaseModel):
    claim_id: UUID
    depth: int


class TraverseEdge(BaseModel):
    source_id: UUID
    target_id: UUID
    relation_type: str


class TraverseResponse(BaseModel):
    nodes: list[TraverseNode]
    edges: list[TraverseEdge]


def create_graph_router() -> APIRouter:
    """Create the graph layer's API router."""
    router = APIRouter()

    @router.get("/edge-types")
    async def list_edge_types(
        category: str | None = Query(None),
        db: AsyncSession = Depends(get_db),
    ) -> list[dict[str, Any]]:
        """List all registered graph edge types with their semantic properties."""
        stmt = select(GraphEdgeType)
        if category is not None:
            stmt = stmt.where(GraphEdgeType.category == category)
        result = await db.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "name": et.name,
                "description": et.description,
                "inverse_name": et.inverse_name,
                "is_transitive": et.is_transitive,
                "is_symmetric": et.is_symmetric,
                "category": et.category,
            }
            for et in rows
        ]

    @router.get("/claims/{claim_id}/neighbors")
    async def get_neighbors(
        claim_id: UUID,
        direction: str = Query("both", pattern="^(both|incoming|outgoing)$"),
        db: AsyncSession = Depends(get_db),
    ) -> dict[str, Any]:
        """Get direct relations for a claim with graph type info."""
        if direction == "outgoing":
            stmt = select(Relation).where(Relation.source_id == claim_id)
        elif direction == "incoming":
            stmt = select(Relation).where(Relation.target_id == claim_id)
        else:
            stmt = select(Relation).where(
                (Relation.source_id == claim_id) | (Relation.target_id == claim_id)
            )
        result = await db.execute(stmt)
        relations = list(result.scalars().all())

        # Fetch edge type metadata for the relation types found
        rel_types = {r.relation_type for r in relations}
        edge_types_map: dict[str, Any] = {}
        if rel_types:
            et_result = await db.execute(
                select(GraphEdgeType).where(GraphEdgeType.name.in_(rel_types))
            )
            for et in et_result.scalars().all():
                edge_types_map[et.name] = {
                    "is_transitive": et.is_transitive,
                    "is_symmetric": et.is_symmetric,
                    "category": et.category,
                    "inverse_name": et.inverse_name,
                }

        neighbors = []
        for r in relations:
            neighbor_id = r.target_id if r.source_id == claim_id else r.source_id
            neighbors.append(
                {
                    "relation_id": str(r.id),
                    "neighbor_id": str(neighbor_id),
                    "relation_type": r.relation_type,
                    "strength": r.strength,
                    "direction": "outgoing" if r.source_id == claim_id else "incoming",
                    "edge_type_info": edge_types_map.get(r.relation_type),
                }
            )

        return {"claim_id": str(claim_id), "neighbors": neighbors}

    @router.post("/traverse", response_model=TraverseResponse)
    async def traverse(
        body: TraverseRequest,
        db: AsyncSession = Depends(get_db),
    ) -> TraverseResponse:
        """Graph traversal with depth/type filters (BFS or DFS)."""
        visited: set[UUID] = set()
        nodes: list[TraverseNode] = []
        edges: list[TraverseEdge] = []

        frontier: deque[tuple[UUID, int]] = deque()
        frontier.append((body.start_id, 0))
        visited.add(body.start_id)
        nodes.append(TraverseNode(claim_id=body.start_id, depth=0))

        while frontier:
            if body.algorithm == "dfs":
                current_id, depth = frontier.pop()
            else:
                current_id, depth = frontier.popleft()

            if depth >= body.max_depth:
                continue

            # Build query for neighbors
            if body.direction == "outgoing":
                stmt = select(Relation).where(Relation.source_id == current_id)
            elif body.direction == "incoming":
                stmt = select(Relation).where(Relation.target_id == current_id)
            else:
                stmt = select(Relation).where(
                    (Relation.source_id == current_id) | (Relation.target_id == current_id)
                )

            if body.relation_types:
                stmt = stmt.where(Relation.relation_type.in_(body.relation_types))

            result = await db.execute(stmt)
            relations = list(result.scalars().all())

            for rel in relations:
                neighbor_id = rel.target_id if rel.source_id == current_id else rel.source_id
                edges.append(
                    TraverseEdge(
                        source_id=rel.source_id,
                        target_id=rel.target_id,
                        relation_type=rel.relation_type,
                    )
                )
                if neighbor_id not in visited:
                    visited.add(neighbor_id)
                    nodes.append(TraverseNode(claim_id=neighbor_id, depth=depth + 1))
                    frontier.append((neighbor_id, depth + 1))

        return TraverseResponse(nodes=nodes, edges=edges)

    return router
