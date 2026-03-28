# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Graph tool router — GET /v1/tools/graph/ endpoint."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.db.session import get_db
from phiacta.tools.graph.repository import (
    enrich_nodes,
    group_edges,
    prune_disconnected,
    traverse_references,
)
from phiacta.tools.graph.schemas import (
    GraphEdge,
    GraphNode,
    GraphRef,
    GraphResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_VALID_MODES = {"ref"}
_VALID_DIRECTIONS = {"outgoing", "incoming", "both"}
_MAX_SEEDS = 20


def _parse_uuids(raw: str) -> list[UUID]:
    """Parse comma-separated UUID string. Raises HTTPException on invalid."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise HTTPException(status_code=422, detail="entry_ids must not be empty")
    if len(parts) > _MAX_SEEDS:
        raise HTTPException(
            status_code=422,
            detail=f"Too many seeds ({len(parts)}). Maximum is {_MAX_SEEDS}.",
        )
    uuids: list[UUID] = []
    for p in parts:
        try:
            uuids.append(UUID(p))
        except ValueError:
            raise HTTPException(
                status_code=422, detail=f"Invalid UUID: {p!r}",
            )
    return uuids


def _parse_csv(raw: str | None) -> list[str] | None:
    """Parse optional comma-separated string into list."""
    if raw is None:
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts if parts else None


@router.get("/", response_model=GraphResponse)
async def get_graph(
    entry_ids: str = Query(..., description="Comma-separated seed entry UUIDs"),
    mode: str = Query("ref", description="Graph mode"),
    depth: int = Query(2, ge=0, le=5),
    direction: str = Query("both", description="Edge direction filter"),
    rel: str | None = Query(None, description="Comma-separated relationship type filter"),
    entry_type: str | None = Query(None, description="Comma-separated entry type filter"),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> GraphResponse:
    """Traverse the reference graph from seed entries.

    Public read — no auth required. Returns nodes and grouped edges
    for the subgraph reachable within ``depth`` hops from the seeds.
    """
    # Validate mode
    if mode not in _VALID_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown mode: {mode!r}. Valid modes: {sorted(_VALID_MODES)}",
        )

    # Validate direction
    if direction not in _VALID_DIRECTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid direction: {direction!r}. Valid: {sorted(_VALID_DIRECTIONS)}",
        )

    seed_ids = _parse_uuids(entry_ids)
    rel_filter = _parse_csv(rel)
    entry_type_filter = _parse_csv(entry_type)

    # Set statement timeout as safety net (PostgreSQL only)
    try:
        await db.execute(text("SET LOCAL statement_timeout = '10s'"))
    except OperationalError:
        pass  # SQLite or other backends — skip timeout

    try:
        node_depths, edge_rows = await traverse_references(
            seed_ids=seed_ids,
            depth=depth,
            direction=direction,
            rel_filter=rel_filter,
            limit=limit,
            db=db,
        )
    except OperationalError:
        logger.warning("Graph traversal timed out for seeds=%s depth=%d", seed_ids, depth)
        raise HTTPException(
            status_code=503,
            detail="Graph traversal timed out. Try reducing depth or narrowing filters.",
        )

    truncated = len(node_depths) >= limit

    # Group edges by unordered node pair
    edges = group_edges(edge_rows)

    # Apply entry_type filter on non-seed nodes
    if entry_type_filter:
        # Need enrichment first to know entry types
        enrichment = await enrich_nodes(node_ids=list(node_depths.keys()), db=db)

        # Remove non-matching non-seed nodes
        filtered_nodes: dict[UUID, int] = {}
        for nid, d in node_depths.items():
            if nid in seed_ids:
                # Seeds always included
                filtered_nodes[nid] = d
            elif nid in enrichment:
                et = enrichment[nid].get("entry_type")
                if et and et in entry_type_filter:
                    filtered_nodes[nid] = d
        node_depths = filtered_nodes

        # Remove edges referencing pruned nodes
        remaining = set(node_depths.keys())
        edges = [
            e for e in edges
            if e["source"] in remaining and e["target"] in remaining
        ]

        # Prune disconnected from seeds
        node_depths, edges = prune_disconnected(
            node_depths=node_depths, edges=edges, seed_ids=seed_ids,
        )
    else:
        enrichment = None

    # Enrich nodes (skip if already done for entry_type filtering)
    if enrichment is None:
        enrichment = await enrich_nodes(node_ids=list(node_depths.keys()), db=db)

    # Build response
    nodes = []
    for nid, d in node_depths.items():
        info = enrichment.get(nid, {})
        nodes.append(GraphNode(
            id=nid,
            title=info.get("title"),
            summary=info.get("summary"),
            entry_type=info.get("entry_type"),
            tags=info.get("tags", []),
            status=info.get("status", "active"),
            depth=d,
        ))

    # Sort nodes by depth for consistent output
    nodes.sort(key=lambda n: (n.depth, str(n.id)))

    graph_edges = [
        GraphEdge(
            source=e["source"],
            target=e["target"],
            refs=[GraphRef(**r) for r in e["refs"]],
        )
        for e in edges
    ]

    # Filter seed_ids to only those that ended up in the graph
    actual_seeds = [sid for sid in seed_ids if sid in node_depths]

    return GraphResponse(
        nodes=nodes,
        edges=graph_edges,
        truncated=truncated,
        seed_ids=actual_seeds,
        mode=mode,
    )
