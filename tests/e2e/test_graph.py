# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for graph tool — reference graph traversal."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import phiacta.extensions.metadata.models  # noqa: F401
import phiacta.extensions.references.models  # noqa: F401
import phiacta.extensions.tags.models  # noqa: F401
import phiacta.extensions.types.models  # noqa: F401

from tests.e2e.conftest import (
    auth_header,
    create_entry,
    register_user,
    set_entry_repo_status,
)

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


@pytest.fixture(autouse=True)
def _mount_routers(client: httpx.AsyncClient) -> None:
    from phiacta.extensions.metadata import router as mr
    from phiacta.extensions.references import router as rr
    from phiacta.extensions.tags import router as tagr
    from phiacta.extensions.types import router as tr
    from phiacta.tools.graph.router import router as gr
    from phiacta.main import app as _app

    _app.include_router(mr, prefix="/v1/extensions/metadata", tags=["metadata"])
    _app.include_router(tr, prefix="/v1/extensions/types", tags=["types"])
    _app.include_router(rr, prefix="/v1/extensions/references", tags=["references"])
    _app.include_router(tagr, prefix="/v1/extensions/tags", tags=["tags"])
    _app.include_router(gr, prefix="/v1/tools/graph", tags=["graph"])
    yield  # type: ignore[misc]
    prefixes = (
        "/v1/extensions/metadata", "/v1/extensions/types",
        "/v1/extensions/references", "/v1/extensions/tags",
        "/v1/tools/graph",
    )
    _app.routes[:] = [
        r for r in _app.routes
        if not (hasattr(r, "path") and any(r.path.startswith(p) for p in prefixes))
    ]


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    auth = await register_user(client, handle=f"graph-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def three_chain(
    authed: AuthedFixture,
    e2e_session_factory: async_sessionmaker[AsyncSession],
) -> tuple[AuthedFixture, dict, dict, dict]:
    """Create A → B → C chain of entries with references."""
    client, _, token = authed
    a = await create_entry(client, token, title="Entry A", entry_type="claim")
    b = await create_entry(client, token, title="Entry B", entry_type="evidence")
    c = await create_entry(client, token, title="Entry C", entry_type="paper")
    for e in (a, b, c):
        await set_entry_repo_status(e2e_session_factory, e["id"], "ready")

    # A → B (supports)
    resp = await client.post(
        f"/v1/extensions/references/{a['id']}",
        json={"target_entry_id": b["id"], "rel": "supports"},
        headers=auth_header(token),
    )
    assert resp.status_code == 201

    # B → C (cites)
    resp = await client.post(
        f"/v1/extensions/references/{b['id']}",
        json={"target_entry_id": c["id"], "rel": "cites"},
        headers=auth_header(token),
    )
    assert resp.status_code == 201

    return authed, a, b, c


class TestGraphResponseShape:
    async def test_returns_200(self, authed: AuthedFixture) -> None:
        client, _, _ = authed
        # Use a random UUID — should return empty graph, not error
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": str(uuid4())},
        )
        assert resp.status_code == 200

    async def test_response_fields(self, authed: AuthedFixture) -> None:
        client, _, _ = authed
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": str(uuid4())},
        )
        data = resp.json()
        assert "nodes" in data
        assert "edges" in data
        assert "truncated" in data
        assert "seed_ids" in data
        assert "mode" in data
        assert data["mode"] == "ref"


class TestGraphTraversal:
    async def test_depth_1_returns_direct_neighbors(
        self, three_chain: tuple[AuthedFixture, dict, dict, dict],
    ) -> None:
        (client, _, _), a, b, c = three_chain
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": a["id"], "depth": 1},
        )
        assert resp.status_code == 200
        data = resp.json()
        node_ids = {n["id"] for n in data["nodes"]}
        # A and B should be present, C should not (depth 2)
        assert a["id"] in node_ids
        assert b["id"] in node_ids
        assert c["id"] not in node_ids

    async def test_depth_2_reaches_full_chain(
        self, three_chain: tuple[AuthedFixture, dict, dict, dict],
    ) -> None:
        (client, _, _), a, b, c = three_chain
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": a["id"], "depth": 2},
        )
        data = resp.json()
        node_ids = {n["id"] for n in data["nodes"]}
        assert a["id"] in node_ids
        assert b["id"] in node_ids
        assert c["id"] in node_ids

    async def test_depth_0_seeds_only(
        self, three_chain: tuple[AuthedFixture, dict, dict, dict],
    ) -> None:
        (client, _, _), a, b, c = three_chain
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": f"{a['id']},{c['id']}", "depth": 0},
        )
        data = resp.json()
        node_ids = {n["id"] for n in data["nodes"]}
        # Only seeds, no expansion
        assert a["id"] in node_ids
        assert c["id"] in node_ids
        # No edge between A and C (they're not directly connected)
        assert len(data["edges"]) == 0


class TestGraphNodeFields:
    async def test_node_has_all_fields(
        self, three_chain: tuple[AuthedFixture, dict, dict, dict],
    ) -> None:
        (client, _, _), a, _, _ = three_chain
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": a["id"], "depth": 1},
        )
        data = resp.json()
        for node in data["nodes"]:
            assert "id" in node
            assert "title" in node
            assert "summary" in node
            assert "entry_type" in node
            assert "tags" in node
            assert "visibility" in node
            assert "depth" in node

    async def test_seed_has_depth_0(
        self, three_chain: tuple[AuthedFixture, dict, dict, dict],
    ) -> None:
        (client, _, _), a, _, _ = three_chain
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": a["id"], "depth": 1},
        )
        seed_node = next(n for n in resp.json()["nodes"] if n["id"] == a["id"])
        assert seed_node["depth"] == 0


class TestGraphEdgeGrouping:
    async def test_parallel_edges_grouped(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Two refs between same pair → one edge with two refs."""
        client, _, token = authed
        a = await create_entry(client, token, title="Edge A")
        b = await create_entry(client, token, title="Edge B")
        for e in (a, b):
            await set_entry_repo_status(e2e_session_factory, e["id"], "ready")

        # Create two refs: A→B supports and A→B cites
        await client.post(
            f"/v1/extensions/references/{a['id']}",
            json={"target_entry_id": b["id"], "rel": "supports"},
            headers=auth_header(token),
        )
        await client.post(
            f"/v1/extensions/references/{a['id']}",
            json={"target_entry_id": b["id"], "rel": "cites"},
            headers=auth_header(token),
        )

        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": a["id"], "depth": 1},
        )
        data = resp.json()
        # Should be exactly 1 edge (grouped)
        assert len(data["edges"]) == 1
        edge = data["edges"][0]
        # With 2 refs
        assert len(edge["refs"]) == 2
        rels = {r["rel"] for r in edge["refs"]}
        assert rels == {"supports", "cites"}

    async def test_edge_has_direction(
        self, three_chain: tuple[AuthedFixture, dict, dict, dict],
    ) -> None:
        (client, _, _), a, b, _ = three_chain
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": a["id"], "depth": 1},
        )
        data = resp.json()
        assert len(data["edges"]) >= 1
        for edge in data["edges"]:
            for ref in edge["refs"]:
                assert ref["direction"] in ("forward", "reverse")


class TestGraphDirectionFilter:
    async def test_outgoing_only(
        self, three_chain: tuple[AuthedFixture, dict, dict, dict],
    ) -> None:
        (client, _, _), a, b, c = three_chain
        # From B, outgoing should find C only
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": b["id"], "depth": 1, "direction": "outgoing"},
        )
        node_ids = {n["id"] for n in resp.json()["nodes"]}
        assert b["id"] in node_ids
        assert c["id"] in node_ids
        assert a["id"] not in node_ids

    async def test_incoming_only(
        self, three_chain: tuple[AuthedFixture, dict, dict, dict],
    ) -> None:
        (client, _, _), a, b, c = three_chain
        # From B, incoming should find A only
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": b["id"], "depth": 1, "direction": "incoming"},
        )
        node_ids = {n["id"] for n in resp.json()["nodes"]}
        assert b["id"] in node_ids
        assert a["id"] in node_ids
        assert c["id"] not in node_ids


class TestGraphRelFilter:
    async def test_filter_by_rel(
        self, three_chain: tuple[AuthedFixture, dict, dict, dict],
    ) -> None:
        (client, _, _), a, b, c = three_chain
        # A→B is "supports", B→C is "cites". Filter to supports only.
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": a["id"], "depth": 2, "rel": "supports"},
        )
        data = resp.json()
        node_ids = {n["id"] for n in data["nodes"]}
        # A and B present (connected by supports), C absent (cites filtered out)
        assert a["id"] in node_ids
        assert b["id"] in node_ids
        # C should be pruned — only reachable via "cites" which is filtered
        assert c["id"] not in node_ids


class TestGraphEntryTypeFilter:
    async def test_filter_keeps_matching_types(
        self, three_chain: tuple[AuthedFixture, dict, dict, dict],
    ) -> None:
        (client, _, _), a, b, c = three_chain
        # A=claim, B=evidence, C=paper. Filter to evidence.
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": a["id"], "depth": 2, "entry_type": "evidence"},
        )
        data = resp.json()
        node_ids = {n["id"] for n in data["nodes"]}
        # A is seed (always included), B matches (evidence), C doesn't (paper)
        assert a["id"] in node_ids
        assert b["id"] in node_ids
        assert c["id"] not in node_ids


class TestGraphIsolatedSeed:
    async def test_seed_with_no_refs(self, authed: AuthedFixture, e2e_session_factory: async_sessionmaker[AsyncSession]) -> None:
        client, _, token = authed
        entry = await create_entry(client, token, title="Lonely")
        await set_entry_repo_status(e2e_session_factory, entry["id"], "ready")

        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": entry["id"], "depth": 2},
        )
        data = resp.json()
        assert len(data["nodes"]) == 1
        assert data["nodes"][0]["id"] == entry["id"]
        assert len(data["edges"]) == 0
        assert data["truncated"] is False


class TestGraphMultipleSeeds:
    async def test_deduplication(
        self, three_chain: tuple[AuthedFixture, dict, dict, dict],
    ) -> None:
        (client, _, _), a, b, c = three_chain
        # Both A and C as seeds at depth 1 — B is reachable from both
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": f"{a['id']},{c['id']}", "depth": 1},
        )
        data = resp.json()
        node_ids = [n["id"] for n in data["nodes"]]
        # B should appear exactly once
        assert node_ids.count(b["id"]) == 1


class TestGraphValidation:
    async def test_invalid_uuid(self, authed: AuthedFixture) -> None:
        client, _, _ = authed
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": "not-a-uuid"},
        )
        assert resp.status_code == 422

    async def test_empty_entry_ids(self, authed: AuthedFixture) -> None:
        client, _, _ = authed
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": ""},
        )
        assert resp.status_code == 422

    async def test_unknown_mode(self, authed: AuthedFixture) -> None:
        client, _, _ = authed
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": str(uuid4()), "mode": "unknown"},
        )
        assert resp.status_code == 422

    async def test_invalid_direction(self, authed: AuthedFixture) -> None:
        client, _, _ = authed
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": str(uuid4()), "direction": "sideways"},
        )
        assert resp.status_code == 422

    async def test_nonexistent_rel_returns_empty(self, three_chain: tuple[AuthedFixture, dict, dict, dict]) -> None:
        (client, _, _), a, _, _ = three_chain
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": a["id"], "depth": 2, "rel": "nonexistent"},
        )
        data = resp.json()
        # Seed appears but no edges
        assert len(data["edges"]) == 0
