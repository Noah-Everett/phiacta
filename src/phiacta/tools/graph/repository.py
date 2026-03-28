# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Graph tool repository — reference graph traversal over extension_references."""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.entry import Entry
from phiacta.extensions.references.models import ExtensionReference

try:
    from phiacta.extensions.metadata.models import ExtensionMetadata
except ImportError:
    ExtensionMetadata = None  # type: ignore[assignment,misc]

try:
    from phiacta.extensions.types.models import ExtensionType
except ImportError:
    ExtensionType = None  # type: ignore[assignment,misc]

try:
    from phiacta.extensions.tags.models import ExtensionTag
except ImportError:
    ExtensionTag = None  # type: ignore[assignment,misc]


async def traverse_references(
    *,
    seed_ids: list[UUID],
    depth: int,
    direction: str,
    rel_filter: list[str] | None,
    limit: int,
    db: AsyncSession,
) -> tuple[dict[UUID, int], list[Row]]:
    """Traverse the reference graph from seeds via iterative BFS.

    Returns (node_id -> min_depth mapping, raw edge rows).

    Uses node-based visited tracking: each node is expanded at most once
    (first reached = minimum depth), keeping work linear in nodes.
    Joins entries at every hop to confirm the entity is an entry.
    Does NOT filter by entry status — archived entries are included.
    """
    if not seed_ids:
        return {}, []

    # Validate seeds are actual entries
    valid_stmt = select(Entry.id).where(Entry.id.in_(seed_ids))
    valid_result = await db.execute(valid_stmt)
    valid_seeds = {row.id for row in valid_result.all()}

    node_depths: dict[UUID, int] = {sid: 0 for sid in seed_ids if sid in valid_seeds}

    if depth == 0 or not node_depths:
        edge_rows = await _fetch_edges(
            node_ids=list(node_depths.keys()),
            direction=direction,
            rel_filter=rel_filter,
            db=db,
        )
        return node_depths, edge_rows

    # Iterative BFS: expand one depth level at a time
    frontier = set(node_depths.keys())

    for current_depth in range(1, depth + 1):
        if not frontier or len(node_depths) >= limit:
            break

        # Find neighbors of the frontier
        neighbors = await _get_neighbors(
            node_ids=list(frontier),
            direction=direction,
            rel_filter=rel_filter,
            db=db,
        )

        # Add unvisited neighbors
        frontier = set()
        for nid in neighbors:
            if nid not in node_depths and len(node_depths) < limit:
                node_depths[nid] = current_depth
                frontier.add(nid)

    # Fetch all edges between the discovered node set
    all_node_ids = list(node_depths.keys())
    edge_rows = await _fetch_edges(
        node_ids=all_node_ids,
        direction=direction,
        rel_filter=rel_filter,
        db=db,
    )

    return node_depths, edge_rows


async def _get_neighbors(
    *,
    node_ids: list[UUID],
    direction: str,
    rel_filter: list[str] | None,
    db: AsyncSession,
) -> set[UUID]:
    """Get all entry neighbors of the given nodes via extension_references.

    Only returns neighbors that are entries (joins entries table).
    """
    if not node_ids:
        return set()

    neighbors: set[UUID] = set()

    if direction in ("outgoing", "both"):
        # Outgoing: from_entity_id in frontier -> to_entity_id is neighbor
        stmt = (
            select(ExtensionReference.to_entity_id)
            .join(Entry, Entry.id == ExtensionReference.to_entity_id)
            .where(ExtensionReference.from_entity_id.in_(node_ids))
        )
        if rel_filter:
            stmt = stmt.where(ExtensionReference.rel.in_(rel_filter))
        result = await db.execute(stmt)
        neighbors.update(row.to_entity_id for row in result.all())

    if direction in ("incoming", "both"):
        # Incoming: to_entity_id in frontier -> from_entity_id is neighbor
        stmt = (
            select(ExtensionReference.from_entity_id)
            .join(Entry, Entry.id == ExtensionReference.from_entity_id)
            .where(ExtensionReference.to_entity_id.in_(node_ids))
        )
        if rel_filter:
            stmt = stmt.where(ExtensionReference.rel.in_(rel_filter))
        result = await db.execute(stmt)
        neighbors.update(row.from_entity_id for row in result.all())

    return neighbors


async def _fetch_edges(
    *,
    node_ids: list[UUID],
    direction: str,
    rel_filter: list[str] | None,
    db: AsyncSession,
) -> list[Row]:
    """Fetch all reference edges where both endpoints are in node_ids."""
    if not node_ids:
        return []

    stmt = select(
        ExtensionReference.id,
        ExtensionReference.from_entity_id,
        ExtensionReference.to_entity_id,
        ExtensionReference.rel,
        ExtensionReference.note,
    ).where(
        ExtensionReference.from_entity_id.in_(node_ids),
        ExtensionReference.to_entity_id.in_(node_ids),
    )

    if rel_filter:
        stmt = stmt.where(ExtensionReference.rel.in_(rel_filter))

    result = await db.execute(stmt)
    return result.all()


async def enrich_nodes(
    *,
    node_ids: list[UUID],
    db: AsyncSession,
) -> dict[UUID, dict]:
    """Enrich node IDs with metadata, type, tags, and status."""
    if not node_ids:
        return {}

    # Base query: entry status
    columns = [Entry.id.label("entry_id"), Entry.status]
    if ExtensionMetadata is not None:
        columns.extend([ExtensionMetadata.title, ExtensionMetadata.summary])
    if ExtensionType is not None:
        columns.append(ExtensionType.entry_type)

    stmt = select(*columns).where(Entry.id.in_(node_ids))

    if ExtensionMetadata is not None:
        stmt = stmt.outerjoin(
            ExtensionMetadata, ExtensionMetadata.entity_id == Entry.id,
        )
    if ExtensionType is not None:
        stmt = stmt.outerjoin(
            ExtensionType, ExtensionType.entity_id == Entry.id,
        )

    result = await db.execute(stmt)
    rows = result.all()

    enriched: dict[UUID, dict] = {}
    for r in rows:
        enriched[r.entry_id] = {
            "status": r.status,
            "title": getattr(r, "title", None),
            "summary": getattr(r, "summary", None),
            "entry_type": getattr(r, "entry_type", None),
        }

    # Tags: single IN-query, grouped in Python
    if ExtensionTag is not None:
        tag_stmt = (
            select(ExtensionTag.entity_id, ExtensionTag.tag)
            .where(ExtensionTag.entity_id.in_(node_ids))
        )
        tag_result = await db.execute(tag_stmt)
        tags_by_id: dict[UUID, list[str]] = defaultdict(list)
        for row in tag_result.all():
            tags_by_id[row.entity_id].append(row.tag)
        for nid, tags in tags_by_id.items():
            if nid in enriched:
                enriched[nid]["tags"] = tags

    return enriched


def group_edges(
    edge_rows: list[Row],
) -> list[dict]:
    """Group raw edge rows by unordered node pair.

    Returns list of edge dicts with source (lower UUID), target (higher UUID),
    and refs list preserving original direction.
    """
    grouped: dict[tuple[UUID, UUID], list[dict]] = defaultdict(list)

    for row in edge_rows:
        from_id = row.from_entity_id
        to_id = row.to_entity_id

        # Consistent ordering: lower UUID string = source
        if str(from_id) <= str(to_id):
            source, target = from_id, to_id
            direction = "forward"
        else:
            source, target = to_id, from_id
            direction = "reverse"

        grouped[(source, target)].append({
            "id": row.id,
            "rel": row.rel,
            "direction": direction,
            "note": row.note,
            "weight": None,
        })

    return [
        {"source": pair[0], "target": pair[1], "refs": refs}
        for pair, refs in grouped.items()
    ]


def prune_disconnected(
    *,
    node_depths: dict[UUID, int],
    edges: list[dict],
    seed_ids: list[UUID],
) -> tuple[dict[UUID, int], list[dict]]:
    """Remove nodes not reachable from seeds through visible edges.

    BFS from seeds through the edge set. Nodes not reached are pruned.
    """
    # Build adjacency from grouped edges
    adj: dict[UUID, set[UUID]] = defaultdict(set)
    for edge in edges:
        s, t = edge["source"], edge["target"]
        adj[s].add(t)
        adj[t].add(s)

    # BFS from seeds
    reachable: set[UUID] = set()
    frontier = [sid for sid in seed_ids if sid in node_depths]
    while frontier:
        node = frontier.pop()
        if node in reachable:
            continue
        reachable.add(node)
        for neighbor in adj.get(node, set()):
            if neighbor not in reachable and neighbor in node_depths:
                frontier.append(neighbor)

    # Prune
    pruned_nodes = {nid: d for nid, d in node_depths.items() if nid in reachable}
    pruned_edges = [
        e for e in edges
        if e["source"] in reachable and e["target"] in reachable
    ]

    return pruned_nodes, pruned_edges
