# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NewPublishing Contributors

from __future__ import annotations

from typing import Any

from fastapi import APIRouter


def create_graph_router() -> APIRouter:
    """Create the graph layer's API router."""
    router = APIRouter()

    @router.get("/edge-types")
    async def list_edge_types() -> list[dict[str, Any]]:
        """List all registered graph edge types with their semantic properties."""
        # TODO: query graph_edge_types table
        return []

    @router.get("/claims/{claim_id}/neighbors")
    async def get_neighbors(claim_id: str) -> dict[str, Any]:
        """Get direct relations for a claim with graph type info."""
        # TODO: join relations with graph_edge_types
        return {"claim_id": claim_id, "neighbors": []}

    @router.post("/traverse")
    async def traverse() -> dict[str, Any]:
        """Graph traversal with depth/type filters and transitivity."""
        # TODO: implement BFS/recursive CTE traversal
        return {"nodes": [], "edges": []}

    return router
