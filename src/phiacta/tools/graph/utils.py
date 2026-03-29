# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Pure-Python graph utilities — no DB access, no model imports.

These functions operate on plain Python data structures returned by
the graph query service.
"""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import Row


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
    """Remove nodes not reachable from seeds through visible edges."""
    adj: dict[UUID, set[UUID]] = defaultdict(set)
    for edge in edges:
        s, t = edge["source"], edge["target"]
        adj[s].add(t)
        adj[t].add(s)

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

    pruned_nodes = {nid: d for nid, d in node_depths.items() if nid in reachable}
    pruned_edges = [
        e for e in edges
        if e["source"] in reachable and e["target"] in reachable
    ]

    return pruned_nodes, pruned_edges
