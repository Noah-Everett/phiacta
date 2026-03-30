# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Graph query service — reference graph traversal and node enrichment.

Contains the DB-access functions previously in tools/graph/repository.py.
Tools call this service instead of importing Entry/extension models directly.
"""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.visibility import discovery_condition
from phiacta.core.models.entry import Entry
try:
    from phiacta.extensions.references.models import ExtensionReference
except ImportError:
    ExtensionReference = None  # type: ignore[assignment,misc]

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
    viewer_id: UUID | None = None,
    db: AsyncSession,
) -> tuple[dict[UUID, int], list[Row]]:
    """Traverse the reference graph from seeds via iterative BFS.

    Returns (node_id -> min_depth mapping, raw edge rows).
    Private entries are only visible to their owner (``viewer_id``).
    """
    if not seed_ids or ExtensionReference is None:
        return {}, []

    valid_stmt = (
        select(Entry.id)
        .where(Entry.id.in_(seed_ids))
        .where(discovery_condition(viewer_id))
    )
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

    frontier = set(node_depths.keys())

    for current_depth in range(1, depth + 1):
        if not frontier or len(node_depths) >= limit:
            break

        neighbors = await _get_neighbors(
            node_ids=list(frontier),
            direction=direction,
            rel_filter=rel_filter,
            viewer_id=viewer_id,
            db=db,
        )

        frontier = set()
        for nid in neighbors:
            if nid not in node_depths and len(node_depths) < limit:
                node_depths[nid] = current_depth
                frontier.add(nid)

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
    viewer_id: UUID | None = None,
    db: AsyncSession,
) -> set[UUID]:
    """Get all entry neighbors visible to the caller."""
    if not node_ids or ExtensionReference is None:
        return set()

    vis = discovery_condition(viewer_id)
    neighbors: set[UUID] = set()

    if direction in ("outgoing", "both"):
        stmt = (
            select(ExtensionReference.to_entity_id)
            .join(Entry, Entry.id == ExtensionReference.to_entity_id)
            .where(ExtensionReference.from_entity_id.in_(node_ids))
            .where(vis)
        )
        if rel_filter:
            stmt = stmt.where(ExtensionReference.rel.in_(rel_filter))
        result = await db.execute(stmt)
        neighbors.update(row.to_entity_id for row in result.all())

    if direction in ("incoming", "both"):
        stmt = (
            select(ExtensionReference.from_entity_id)
            .join(Entry, Entry.id == ExtensionReference.from_entity_id)
            .where(ExtensionReference.to_entity_id.in_(node_ids))
            .where(vis)
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
    if not node_ids or ExtensionReference is None:
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
    """Enrich node IDs with metadata, type, tags, and visibility."""
    if not node_ids:
        return {}

    columns = [Entry.id.label("entry_id"), Entry.visibility]
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
            "visibility": r.visibility,
            "title": getattr(r, "title", None),
            "summary": getattr(r, "summary", None),
            "entry_type": getattr(r, "entry_type", None),
        }

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
