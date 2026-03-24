# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for entry ref endpoints (read-only).

Entry refs are git-derived — there is no POST endpoint. Tests create
refs via the DB session factory and verify read endpoints.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from phiacta.core.models.entry_ref import EntryRef
from tests.e2e.conftest import auth_header, register_user

type RefsFixture = tuple[httpx.AsyncClient, str, str, str, str]


async def _create_ref_in_db(
    session_factory: async_sessionmaker[AsyncSession],
    from_entry_id: str,
    to_entry_id: str,
    rel: str,
) -> str:
    """Insert an EntryRef directly and return its id."""
    async with session_factory() as session:
        ref = EntryRef(
            from_entry_id=UUID(from_entry_id),
            to_entry_id=UUID(to_entry_id),
            rel=rel,
        )
        session.add(ref)
        await session.commit()
        await session.refresh(ref)
        return str(ref.id)


@pytest.fixture
async def refs_fixture(
    client: httpx.AsyncClient,
    e2e_session_factory: async_sessionmaker[AsyncSession],
) -> RefsFixture:
    """Create a user, two entries, and a ref between them.

    Returns (client, entry_a_id, entry_b_id, ref_id, token).
    """
    uid = uuid4().hex[:8]
    auth = await register_user(client, handle=f"ref-{uid}")
    token = auth["access_token"]
    headers = auth_header(token)

    resp_a = await client.post("/v1/entries", json={"title": "Entry A"}, headers=headers)
    resp_b = await client.post("/v1/entries", json={"title": "Entry B"}, headers=headers)
    entry_a = resp_a.json()["id"]
    entry_b = resp_b.json()["id"]

    ref_id = await _create_ref_in_db(e2e_session_factory, entry_a, entry_b, "supports")
    return client, entry_a, entry_b, ref_id, token


class TestPostEndpointRemoved:
    async def test_post_returns_method_not_allowed(self, client: httpx.AsyncClient) -> None:
        """POST /v1/entry-refs no longer exists — refs are git-derived only."""
        resp = await client.post("/v1/entry-refs", json={
            "from_entry_id": str(uuid4()),
            "to_entry_id": str(uuid4()),
            "rel": "supports",
        })
        assert resp.status_code == 405


class TestListEntryRefs:
    async def test_list_refs_empty(self, client: httpx.AsyncClient) -> None:
        resp = await client.get("/v1/entry-refs")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    async def test_list_refs_by_from_entry(self, refs_fixture: RefsFixture) -> None:
        client, entry_a, _, _, _ = refs_fixture
        resp = await client.get("/v1/entry-refs", params={"from_entry_id": entry_a})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["from_entry_id"] == entry_a
        assert data["total"] == 1

    async def test_list_refs_by_rel(self, refs_fixture: RefsFixture) -> None:
        client, _, _, _, _ = refs_fixture
        resp = await client.get("/v1/entry-refs", params={"rel": "supports"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["total"] == 1


class TestGetEntryRef:
    async def test_get_ref(self, refs_fixture: RefsFixture) -> None:
        client, _, _, ref_id, _ = refs_fixture
        resp = await client.get(f"/v1/entry-refs/{ref_id}")
        assert resp.status_code == 200
        assert resp.json()["rel"] == "supports"

    async def test_get_ref_not_found(self, client: httpx.AsyncClient) -> None:
        resp = await client.get(f"/v1/entry-refs/{uuid4()}")
        assert resp.status_code == 404


class TestListEntryRefsPagination:
    async def test_list_refs_by_to_entry(self, refs_fixture: RefsFixture) -> None:
        """Filter by to_entry_id returns refs pointing TO that entry."""
        client, _, entry_b, _, _ = refs_fixture
        resp = await client.get("/v1/entry-refs", params={"to_entry_id": entry_b})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["to_entry_id"] == entry_b
        assert data["total"] == 1

    async def test_list_refs_pagination_limit(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Pagination limit and offset work correctly."""
        uid = uuid4().hex[:8]
        auth = await register_user(client, handle=f"refpage-{uid}")
        token = auth["access_token"]
        headers = auth_header(token)

        # Create 3 entries
        entries = []
        for i in range(3):
            resp = await client.post(
                "/v1/entries", json={"title": f"Ref Page {i}"}, headers=headers,
            )
            entries.append(resp.json()["id"])

        # Create 3 refs: 0->1, 0->2, 1->2
        for from_id, to_id, rel in [
            (entries[0], entries[1], "supports"),
            (entries[0], entries[2], "supports"),
            (entries[1], entries[2], "contradicts"),
        ]:
            await _create_ref_in_db(e2e_session_factory, from_id, to_id, rel)

        # Fetch with limit=2
        resp = await client.get("/v1/entry-refs", params={"limit": 2, "offset": 0})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] == 3

        # Fetch offset=2 to get the remaining 1
        resp = await client.get("/v1/entry-refs", params={"limit": 2, "offset": 2})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["total"] == 3

    async def test_list_refs_no_filter_returns_all(
        self,
        refs_fixture: RefsFixture,
    ) -> None:
        """GET /entry-refs with no filter returns all refs."""
        client, _, _, _, _ = refs_fixture
        resp = await client.get("/v1/entry-refs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert len(data["items"]) == data["total"]


class TestEntryReferences:
    async def test_get_entry_references(self, refs_fixture: RefsFixture) -> None:
        client, entry_a, _, _, _ = refs_fixture
        resp = await client.get(f"/v1/entries/{entry_a}/references")
        assert resp.status_code == 200
        refs = resp.json()
        assert len(refs) == 1
        assert refs[0]["rel"] == "supports"

    async def test_get_entry_references_direction(self, refs_fixture: RefsFixture) -> None:
        client, _, entry_b, _, _ = refs_fixture

        # entry_b has incoming ref
        resp = await client.get(
            f"/v1/entries/{entry_b}/references", params={"direction": "incoming"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        # entry_b has no outgoing ref
        resp = await client.get(
            f"/v1/entries/{entry_b}/references", params={"direction": "outgoing"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 0
