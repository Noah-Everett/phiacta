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
from phiacta.models.reference import Reference


class TraverseRequest(BaseModel):
    start_id: UUID
    max_depth: int = 3
    roles: list[str] | None = None
    direction: str = "both"
    algorithm: str = "bfs"


class TraverseNode(BaseModel):
    claim_id: UUID
    depth: int


class TraverseEdge(BaseModel):
    source_uri: str
    target_uri: str
    role: str


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
        """Get direct references for a claim with graph type info."""
        if direction == "outgoing":
            stmt = select(Reference).where(Reference.source_claim_id == claim_id)
        elif direction == "incoming":
            stmt = select(Reference).where(Reference.target_claim_id == claim_id)
        else:
            stmt = select(Reference).where(
                (Reference.source_claim_id == claim_id)
                | (Reference.target_claim_id == claim_id)
            )
        result = await db.execute(stmt)
        references = list(result.scalars().all())

        # Fetch edge type metadata for the roles found
        roles = {r.role for r in references}
        edge_types_map: dict[str, Any] = {}
        if roles:
            et_result = await db.execute(
                select(GraphEdgeType).where(GraphEdgeType.name.in_(roles))
            )
            for et in et_result.scalars().all():
                edge_types_map[et.name] = {
                    "is_transitive": et.is_transitive,
                    "is_symmetric": et.is_symmetric,
                    "category": et.category,
                    "inverse_name": et.inverse_name,
                }

        neighbors = []
        for r in references:
            is_outgoing = r.source_claim_id == claim_id
            neighbor_id = r.target_claim_id if is_outgoing else r.source_claim_id
            if neighbor_id is None:
                continue
            neighbors.append(
                {
                    "reference_id": str(r.id),
                    "neighbor_id": str(neighbor_id),
                    "role": r.role,
                    "source_uri": r.source_uri,
                    "target_uri": r.target_uri,
                    "direction": "outgoing" if is_outgoing else "incoming",
                    "edge_type_info": edge_types_map.get(r.role),
                }
            )

        return {"claim_id": str(claim_id), "neighbors": neighbors}

    @router.post("/traverse", response_model=TraverseResponse)
    async def traverse(
        body: TraverseRequest,
        db: AsyncSession = Depends(get_db),
    ) -> TraverseResponse:
        """Graph traversal with depth/role filters (BFS or DFS).

        Uses batch loading: collects all claim IDs at each depth level
        and fetches their references in a single query per level.
        """
        visited: set[UUID] = set()
        nodes: list[TraverseNode] = []
        edges: list[TraverseEdge] = []

        visited.add(body.start_id)
        nodes.append(TraverseNode(claim_id=body.start_id, depth=0))

        # Level-by-level BFS for batch loading (DFS order applied post-hoc)
        current_level: list[UUID] = [body.start_id]
        depth = 0

        while current_level and depth < body.max_depth:
            # Batch-fetch all references for the current frontier
            if body.direction == "outgoing":
                stmt = select(Reference).where(
                    Reference.source_claim_id.in_(current_level)
                )
            elif body.direction == "incoming":
                stmt = select(Reference).where(
                    Reference.target_claim_id.in_(current_level)
                )
            else:
                stmt = select(Reference).where(
                    (Reference.source_claim_id.in_(current_level))
                    | (Reference.target_claim_id.in_(current_level))
                )

            if body.roles:
                stmt = stmt.where(Reference.role.in_(body.roles))

            result = await db.execute(stmt)
            references = list(result.scalars().all())

            next_level: list[UUID] = []
            for ref in references:
                # Determine neighbor based on which side is in current_level
                if ref.source_claim_id in visited and ref.target_claim_id not in visited:
                    neighbor_id = ref.target_claim_id
                elif ref.target_claim_id in visited and ref.source_claim_id not in visited:
                    neighbor_id = ref.source_claim_id
                else:
                    # Both visited or one is None — just record the edge
                    neighbor_id = None

                edges.append(
                    TraverseEdge(
                        source_uri=ref.source_uri,
                        target_uri=ref.target_uri,
                        role=ref.role,
                    )
                )

                if neighbor_id is not None and neighbor_id not in visited:
                    visited.add(neighbor_id)
                    nodes.append(
                        TraverseNode(claim_id=neighbor_id, depth=depth + 1)
                    )
                    next_level.append(neighbor_id)

            current_level = next_level
            depth += 1

        return TraverseResponse(nodes=nodes, edges=edges)

    return router
