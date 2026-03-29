# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for graph traversal visibility with the new visibility model.

Tests that private entries are excluded from graph traversal for non-owners,
that traversal stops at private entries, and that owners can traverse their
own private entries.
"""

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def set_entry_visibility(
    session_factory: async_sessionmaker[AsyncSession],
    entry_id: str,
    visibility: str,
) -> None:
    """Set an entry's visibility directly in the DB."""
    from phiacta.core.models.entry import Entry
    from sqlalchemy import select
    from uuid import UUID

    async with session_factory() as session:
        result = await session.execute(
            select(Entry).where(Entry.id == UUID(entry_id))
        )
        entry = result.scalar_one()
        entry.visibility = visibility
        await session.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
async def owner(client: httpx.AsyncClient) -> AuthedFixture:
    auth = await register_user(client, handle=f"gvis-owner-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def other_user(client: httpx.AsyncClient) -> AuthedFixture:
    auth = await register_user(client, handle=f"gvis-other-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGraphPrivateVisibility:
    """Scenario: Private entries excluded from graph traversal for non-owners."""

    async def test_private_seed_excluded_for_non_owner(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        client, _, owner_token = owner
        entry = await create_entry(client, owner_token, title="Private Seed")
        await set_entry_repo_status(e2e_session_factory, entry["id"], "ready")
        await set_entry_visibility(e2e_session_factory, entry["id"], "private")

        _, _, other_token = other_user
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": entry["id"], "depth": 2},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        node_ids = {n["id"] for n in data["nodes"]}
        assert entry["id"] not in node_ids

    async def test_traversal_stops_at_private_entry(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """A -> B -> C, where B is private. Non-owner from A: sees A only."""
        client, _, owner_token = owner

        entry_a = await create_entry(client, owner_token, title="Graph Public A")
        entry_b = await create_entry(client, owner_token, title="Graph Private B")
        entry_c = await create_entry(client, owner_token, title="Graph Public C")

        for e in (entry_a, entry_b, entry_c):
            await set_entry_repo_status(e2e_session_factory, e["id"], "ready")

        resp = await client.post(
            f"/v1/extensions/references/{entry_a['id']}",
            json={"target_entry_id": entry_b["id"], "rel": "supports"},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 201

        resp = await client.post(
            f"/v1/extensions/references/{entry_b['id']}",
            json={"target_entry_id": entry_c["id"], "rel": "cites"},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 201

        await set_entry_visibility(e2e_session_factory, entry_b["id"], "private")

        _, _, other_token = other_user
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": entry_a["id"], "depth": 2},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        node_ids = {n["id"] for n in data["nodes"]}

        assert entry_a["id"] in node_ids
        assert entry_b["id"] not in node_ids
        assert entry_c["id"] not in node_ids

    async def test_edges_to_private_excluded_for_non_owner(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """A -> B, B private. Non-owner from A: no edge to B."""
        client, _, owner_token = owner

        entry_a = await create_entry(client, owner_token, title="Edge Public A")
        entry_b = await create_entry(client, owner_token, title="Edge Private B")

        for e in (entry_a, entry_b):
            await set_entry_repo_status(e2e_session_factory, e["id"], "ready")

        resp = await client.post(
            f"/v1/extensions/references/{entry_a['id']}",
            json={"target_entry_id": entry_b["id"], "rel": "supports"},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 201

        await set_entry_visibility(e2e_session_factory, entry_b["id"], "private")

        _, _, other_token = other_user
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": entry_a["id"], "depth": 1},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 200
        data = resp.json()

        for edge in data["edges"]:
            assert edge["source"] != entry_b["id"]
            assert edge["target"] != entry_b["id"]

        node_ids = {n["id"] for n in data["nodes"]}
        assert entry_b["id"] not in node_ids

    async def test_owner_sees_private_entries_in_graph(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Owner sees their private entries in graph results."""
        client, _, owner_token = owner

        entry_a = await create_entry(client, owner_token, title="Owner Graph A")
        entry_b = await create_entry(client, owner_token, title="Owner Graph B Private")

        for e in (entry_a, entry_b):
            await set_entry_repo_status(e2e_session_factory, e["id"], "ready")

        resp = await client.post(
            f"/v1/extensions/references/{entry_a['id']}",
            json={"target_entry_id": entry_b["id"], "rel": "cites"},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 201

        await set_entry_visibility(e2e_session_factory, entry_b["id"], "private")

        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": entry_a["id"], "depth": 1},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        node_ids = {n["id"] for n in data["nodes"]}
        assert entry_a["id"] in node_ids
        assert entry_b["id"] in node_ids
        assert len(data["edges"]) >= 1

    async def test_graph_node_enrichment_excludes_private_metadata(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Private entry metadata must not leak through graph node enrichment."""
        client, _, owner_token = owner

        entry_a = await create_entry(client, owner_token, title="Enrichment Public A")
        entry_b = await create_entry(
            client, owner_token,
            title="Secret Private Title That Must Not Leak",
            summary="Secret summary that must not leak",
        )

        for e in (entry_a, entry_b):
            await set_entry_repo_status(e2e_session_factory, e["id"], "ready")

        resp = await client.post(
            f"/v1/extensions/references/{entry_a['id']}",
            json={"target_entry_id": entry_b["id"], "rel": "cites"},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 201

        await set_entry_visibility(e2e_session_factory, entry_b["id"], "private")

        _, _, other_token = other_user
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": entry_a["id"], "depth": 1},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 200
        data = resp.json()

        response_text = str(data)
        assert "Secret Private Title That Must Not Leak" not in response_text
        assert "Secret summary that must not leak" not in response_text
