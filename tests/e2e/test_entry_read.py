# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for entry read API — list and detail (NEV-120).

Tests the full API contract for:
- GET /v1/entries  — paginated list, public (no auth required)
- GET /v1/entries/{entry_id}  — detail with refs, public (no auth required)

These tests exercise the real FastAPI app with a test database, creating
entries and refs through the API/DB fixtures, then verifying the read
endpoints return correct shapes, pagination, filtering, and ref data.
"""

from __future__ import annotations

from typing import TypeAlias
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from phiacta.models.entry import Entry
from phiacta.models.entry_ref import EntryRef
from tests.e2e.conftest import auth_header, register_agent

AuthedFixture: TypeAlias = tuple[httpx.AsyncClient, dict, str]


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    """Register an agent and return (client, agent_data, token)."""
    uid = uuid4().hex[:8]
    auth = await register_agent(
        client, handle=f"read-{uid}", email=f"read-{uid}@example.com"
    )
    return client, auth["agent"], auth["access_token"]


async def _create_entry(
    client: httpx.AsyncClient,
    token: str,
    *,
    title: str = "Test Entry",
    layout_hint: str | None = None,
    tags: list[str] | None = None,
    content_format: str = "markdown",
    summary: str | None = None,
    license_: str | None = None,
) -> dict:
    """Create an entry via the API and return the response JSON."""
    body: dict = {"title": title, "content_format": content_format}
    if layout_hint is not None:
        body["layout_hint"] = layout_hint
    if tags is not None:
        body["tags"] = tags
    if summary is not None:
        body["summary"] = summary
    if license_ is not None:
        body["license"] = license_
    resp = await client.post("/v1/entries", json=body, headers=auth_header(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _insert_entry_ref(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    from_entry_id: str,
    to_entry_id: str,
    rel: str = "evidence",
    version_sha: str | None = None,
    note: str | None = None,
) -> dict:
    """Insert an EntryRef directly into the DB (no public API for ref creation).

    Returns a dict with the ref fields for assertion.
    """
    ref_id = uuid4()
    async with session_factory() as session:
        ref = EntryRef(
            id=ref_id,
            from_entry_id=UUID(from_entry_id),
            to_entry_id=UUID(to_entry_id),
            rel=rel,
            version_sha=version_sha,
            note=note,
        )
        session.add(ref)
        await session.commit()
        # Re-fetch to get server-generated created_at
        result = await session.execute(
            select(EntryRef).where(EntryRef.id == ref_id)
        )
        saved = result.scalar_one()
        return {
            "id": str(saved.id),
            "from_entry_id": str(saved.from_entry_id),
            "to_entry_id": str(saved.to_entry_id),
            "rel": saved.rel,
            "version_sha": saved.version_sha,
            "note": saved.note,
            "created_at": saved.created_at.isoformat() if saved.created_at else None,
        }


async def _archive_entry(
    session_factory: async_sessionmaker[AsyncSession],
    entry_id: str,
) -> None:
    """Set an entry's status to 'archived' directly in the DB."""
    async with session_factory() as session:
        result = await session.execute(
            select(Entry).where(Entry.id == UUID(entry_id))
        )
        entry = result.scalar_one()
        entry.status = "archived"
        await session.commit()


# ---------------------------------------------------------------------------
# GET /v1/entries — List endpoint
# ---------------------------------------------------------------------------


class TestListEntriesEmpty:
    """Scenario: Listing entries when the database is empty."""

    async def test_empty_database_returns_empty_list(
        self, client: httpx.AsyncClient
    ) -> None:
        """Empty DB returns items=[], total=0, has_more=false."""
        resp = await client.get("/v1/entries")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["has_more"] is False

    async def test_empty_database_envelope_fields(
        self, client: httpx.AsyncClient
    ) -> None:
        """Empty response includes all PaginatedResponse envelope fields."""
        resp = await client.get("/v1/entries")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert "has_more" in data
        assert data["limit"] == 50  # default
        assert data["offset"] == 0  # default


class TestListEntriesWithData:
    """Scenario: Listing entries returns data sorted and shaped correctly."""

    async def test_list_returns_entries_sorted_by_created_at_desc(
        self, authed: AuthedFixture
    ) -> None:
        """Entries are returned newest first (created_at DESC)."""
        client, _, token = authed
        titles = ["First Created", "Second Created", "Third Created"]
        for title in titles:
            await _create_entry(client, token, title=title)

        resp = await client.get("/v1/entries")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3
        # Newest first
        assert data["items"][0]["title"] == "Third Created"
        assert data["items"][1]["title"] == "Second Created"
        assert data["items"][2]["title"] == "First Created"

    async def test_list_does_not_require_authentication(
        self, authed: AuthedFixture
    ) -> None:
        """GET /v1/entries is public, no auth header needed."""
        client, _, token = authed
        await _create_entry(client, token, title="Public Entry")

        # Request without auth header
        resp = await client.get("/v1/entries")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

    async def test_list_item_shape_has_all_expected_fields(
        self, authed: AuthedFixture
    ) -> None:
        """Each list item has all Entry fields EXCEPT content_cache."""
        client, agent, token = authed
        await _create_entry(
            client,
            token,
            title="Shape Check Entry",
            layout_hint="theorem",
            tags=["math", "algebra"],
            content_format="latex",
            summary="A theorem about groups.",
            license_="CC-BY-4.0",
        )

        resp = await client.get("/v1/entries")
        assert resp.status_code == 200
        item = resp.json()["items"][0]

        # All Entry fields present
        assert "id" in item
        assert "title" in item
        assert "layout_hint" in item
        assert "tags" in item
        assert "summary" in item
        assert "license" in item
        assert "content_format" in item
        assert "schema_version" in item
        assert "forgejo_repo_id" in item
        assert "repo_name" in item
        assert "current_head_sha" in item
        assert "repo_status" in item
        assert "status" in item
        assert "created_by" in item
        assert "created_at" in item
        assert "updated_at" in item

        # Verify field values are correct, not just present
        assert item["title"] == "Shape Check Entry"
        assert item["layout_hint"] == "theorem"
        assert item["tags"] == ["math", "algebra"]
        assert item["content_format"] == "latex"
        assert item["summary"] == "A theorem about groups."
        assert item["license"] == "CC-BY-4.0"
        assert item["created_by"] == agent["id"]

    async def test_list_item_excludes_content_cache(
        self, authed: AuthedFixture
    ) -> None:
        """EntryListItem must NOT include content_cache (performance)."""
        client, _, token = authed
        await _create_entry(client, token, title="No Content Cache Entry")

        resp = await client.get("/v1/entries")
        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert "content_cache" not in item


class TestListEntriesPagination:
    """Scenario: Pagination works correctly with limit, offset, and has_more."""

    async def test_pagination_first_page(self, authed: AuthedFixture) -> None:
        """limit=2 with 5 entries returns 2 items, total=5, has_more=true."""
        client, _, token = authed
        for i in range(5):
            await _create_entry(client, token, title=f"Paginated Entry {i}")

        resp = await client.get("/v1/entries", params={"limit": 2, "offset": 0})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] == 5
        assert data["limit"] == 2
        assert data["offset"] == 0
        assert data["has_more"] is True

    async def test_pagination_last_page_partial(self, authed: AuthedFixture) -> None:
        """limit=2, offset=4 with 5 entries returns 1 item, has_more=false."""
        client, _, token = authed
        for i in range(5):
            await _create_entry(client, token, title=f"Last Page Entry {i}")

        resp = await client.get("/v1/entries", params={"limit": 2, "offset": 4})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["total"] == 5
        assert data["has_more"] is False

    async def test_pagination_exact_boundary(self, authed: AuthedFixture) -> None:
        """limit=5, offset=0 with exactly 5 entries returns has_more=false."""
        client, _, token = authed
        for i in range(5):
            await _create_entry(client, token, title=f"Boundary Entry {i}")

        resp = await client.get("/v1/entries", params={"limit": 5, "offset": 0})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 5
        assert data["total"] == 5
        assert data["has_more"] is False

    async def test_pagination_has_more_true_at_boundary_minus_one(
        self, authed: AuthedFixture
    ) -> None:
        """limit=4, offset=0 with 5 entries returns has_more=true (4+0 < 5)."""
        client, _, token = authed
        for i in range(5):
            await _create_entry(client, token, title=f"Boundary-1 Entry {i}")

        resp = await client.get("/v1/entries", params={"limit": 4, "offset": 0})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 4
        assert data["total"] == 5
        assert data["has_more"] is True

    async def test_pagination_offset_beyond_total(
        self, authed: AuthedFixture
    ) -> None:
        """Offset beyond total returns empty items with correct total."""
        client, _, token = authed
        for i in range(3):
            await _create_entry(client, token, title=f"Beyond Entry {i}")

        resp = await client.get("/v1/entries", params={"limit": 10, "offset": 100})
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 3
        assert data["has_more"] is False

    async def test_pagination_second_page_items_differ_from_first(
        self, authed: AuthedFixture
    ) -> None:
        """Page 2 returns different entries than page 1."""
        client, _, token = authed
        for i in range(6):
            await _create_entry(client, token, title=f"Paged Entry {i}")

        page1 = await client.get("/v1/entries", params={"limit": 3, "offset": 0})
        page2 = await client.get("/v1/entries", params={"limit": 3, "offset": 3})
        assert page1.status_code == 200
        assert page2.status_code == 200

        page1_ids = {item["id"] for item in page1.json()["items"]}
        page2_ids = {item["id"] for item in page2.json()["items"]}
        assert len(page1_ids) == 3
        assert len(page2_ids) == 3
        assert page1_ids.isdisjoint(page2_ids), "Pages must not overlap"

    async def test_default_limit_is_50(self, client: httpx.AsyncClient) -> None:
        """When no limit is specified, default is 50."""
        resp = await client.get("/v1/entries")
        assert resp.status_code == 200
        assert resp.json()["limit"] == 50

    async def test_default_offset_is_0(self, client: httpx.AsyncClient) -> None:
        """When no offset is specified, default is 0."""
        resp = await client.get("/v1/entries")
        assert resp.status_code == 200
        assert resp.json()["offset"] == 0


class TestListEntriesPaginationValidation:
    """Scenario: Invalid pagination parameters are rejected."""

    async def test_limit_zero_returns_422(self, client: httpx.AsyncClient) -> None:
        """limit=0 violates min=1 constraint."""
        resp = await client.get("/v1/entries", params={"limit": 0})
        assert resp.status_code == 422

    async def test_limit_negative_returns_422(self, client: httpx.AsyncClient) -> None:
        """Negative limit is rejected."""
        resp = await client.get("/v1/entries", params={"limit": -1})
        assert resp.status_code == 422

    async def test_limit_201_returns_422(self, client: httpx.AsyncClient) -> None:
        """limit=201 exceeds max=200."""
        resp = await client.get("/v1/entries", params={"limit": 201})
        assert resp.status_code == 422

    async def test_limit_200_is_accepted(self, client: httpx.AsyncClient) -> None:
        """limit=200 is the maximum allowed value."""
        resp = await client.get("/v1/entries", params={"limit": 200})
        assert resp.status_code == 200
        assert resp.json()["limit"] == 200

    async def test_limit_1_is_accepted(self, client: httpx.AsyncClient) -> None:
        """limit=1 is the minimum allowed value."""
        resp = await client.get("/v1/entries", params={"limit": 1})
        assert resp.status_code == 200
        assert resp.json()["limit"] == 1

    async def test_negative_offset_returns_422(
        self, client: httpx.AsyncClient
    ) -> None:
        """Negative offset is rejected."""
        resp = await client.get("/v1/entries", params={"offset": -1})
        assert resp.status_code == 422


class TestListEntriesLayoutHintFilter:
    """Scenario: Filtering by layout_hint returns only matching entries."""

    async def test_layout_hint_filter(self, authed: AuthedFixture) -> None:
        """Only entries with matching layout_hint are returned."""
        client, _, token = authed
        await _create_entry(client, token, title="A Law", layout_hint="law")
        await _create_entry(client, token, title="A Theorem", layout_hint="theorem")
        await _create_entry(client, token, title="Another Law", layout_hint="law")

        resp = await client.get("/v1/entries", params={"layout_hint": "law"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2
        for item in data["items"]:
            assert item["layout_hint"] == "law"

    async def test_layout_hint_filter_no_matches(
        self, authed: AuthedFixture
    ) -> None:
        """layout_hint with no matches returns empty with total=0."""
        client, _, token = authed
        await _create_entry(client, token, title="A Law", layout_hint="law")

        resp = await client.get(
            "/v1/entries", params={"layout_hint": "nonexistent-hint"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_no_layout_hint_returns_all(self, authed: AuthedFixture) -> None:
        """Omitting layout_hint returns entries regardless of their layout_hint."""
        client, _, token = authed
        await _create_entry(client, token, title="Law", layout_hint="law")
        await _create_entry(client, token, title="Theorem", layout_hint="theorem")
        await _create_entry(client, token, title="No Hint")

        resp = await client.get("/v1/entries")
        assert resp.status_code == 200
        assert resp.json()["total"] == 3


class TestListEntriesStatusFilter:
    """Scenario: Default status=active excludes archived; status=all includes both."""

    async def test_default_status_excludes_archived(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Default request (no status param) returns only active entries."""
        client, _, token = authed
        active_entry = await _create_entry(
            client, token, title="Active Entry"
        )
        archived_entry = await _create_entry(
            client, token, title="Archived Entry"
        )
        await _archive_entry(e2e_session_factory, archived_entry["id"])

        resp = await client.get("/v1/entries")
        assert resp.status_code == 200
        data = resp.json()
        entry_ids = {item["id"] for item in data["items"]}
        assert active_entry["id"] in entry_ids
        assert archived_entry["id"] not in entry_ids

    async def test_status_active_returns_only_active(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Explicit status=active returns only active entries."""
        client, _, token = authed
        active = await _create_entry(client, token, title="Explicit Active")
        archived = await _create_entry(client, token, title="Explicit Archived")
        await _archive_entry(e2e_session_factory, archived["id"])

        resp = await client.get("/v1/entries", params={"status": "active"})
        assert resp.status_code == 200
        data = resp.json()
        entry_ids = {item["id"] for item in data["items"]}
        assert active["id"] in entry_ids
        assert archived["id"] not in entry_ids

    async def test_status_archived_returns_only_archived(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """status=archived returns only archived entries."""
        client, _, token = authed
        await _create_entry(client, token, title="Still Active")
        to_archive = await _create_entry(client, token, title="To Archive")
        await _archive_entry(e2e_session_factory, to_archive["id"])

        resp = await client.get("/v1/entries", params={"status": "archived"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        entry_ids = {item["id"] for item in data["items"]}
        assert to_archive["id"] in entry_ids
        # Active entries must not appear
        for item in data["items"]:
            assert item["status"] == "archived"

    async def test_status_all_returns_both_active_and_archived(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """status=all returns both active and archived entries."""
        client, _, token = authed
        active = await _create_entry(client, token, title="All-filter Active")
        archived = await _create_entry(client, token, title="All-filter Archived")
        await _archive_entry(e2e_session_factory, archived["id"])

        resp = await client.get("/v1/entries", params={"status": "all"})
        assert resp.status_code == 200
        data = resp.json()
        entry_ids = {item["id"] for item in data["items"]}
        assert active["id"] in entry_ids
        assert archived["id"] in entry_ids


class TestListEntriesCombinedFilters:
    """Scenario: Filters work correctly in combination."""

    async def test_layout_hint_plus_status_filter(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """layout_hint + default status filters work together."""
        client, _, token = authed
        active_law = await _create_entry(
            client, token, title="Active Law", layout_hint="law"
        )
        archived_law = await _create_entry(
            client, token, title="Archived Law", layout_hint="law"
        )
        active_theorem = await _create_entry(
            client, token, title="Active Theorem", layout_hint="theorem"
        )
        await _archive_entry(e2e_session_factory, archived_law["id"])

        # Default status (active) + layout_hint=law
        resp = await client.get("/v1/entries", params={"layout_hint": "law"})
        assert resp.status_code == 200
        data = resp.json()
        entry_ids = {item["id"] for item in data["items"]}
        assert active_law["id"] in entry_ids
        assert archived_law["id"] not in entry_ids
        assert active_theorem["id"] not in entry_ids

    async def test_layout_hint_plus_status_all(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """layout_hint + status=all returns both active and archived with that hint."""
        client, _, token = authed
        active_law = await _create_entry(
            client, token, title="Active Law 2", layout_hint="law"
        )
        archived_law = await _create_entry(
            client, token, title="Archived Law 2", layout_hint="law"
        )
        await _archive_entry(e2e_session_factory, archived_law["id"])
        await _create_entry(
            client, token, title="Active Theorem 2", layout_hint="theorem"
        )

        resp = await client.get(
            "/v1/entries", params={"layout_hint": "law", "status": "all"}
        )
        assert resp.status_code == 200
        data = resp.json()
        entry_ids = {item["id"] for item in data["items"]}
        assert active_law["id"] in entry_ids
        assert archived_law["id"] in entry_ids
        assert data["total"] == 2

    async def test_pagination_with_layout_hint_filter(
        self, authed: AuthedFixture
    ) -> None:
        """Pagination applies after filtering: total reflects filtered count."""
        client, _, token = authed
        for i in range(4):
            await _create_entry(
                client, token, title=f"Law {i}", layout_hint="law"
            )
        await _create_entry(
            client, token, title="Theorem", layout_hint="theorem"
        )

        resp = await client.get(
            "/v1/entries", params={"layout_hint": "law", "limit": 2}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] == 4  # Only law entries counted
        assert data["has_more"] is True


# ---------------------------------------------------------------------------
# GET /v1/entries/{entry_id} — Detail endpoint
# ---------------------------------------------------------------------------


class TestGetEntryDetail:
    """Scenario: Getting a single entry returns full detail with refs."""

    async def test_get_entry_returns_full_response(
        self, authed: AuthedFixture
    ) -> None:
        """Detail returns all EntryResponse fields including content_cache."""
        client, agent, token = authed
        entry = await _create_entry(
            client,
            token,
            title="Detailed Entry",
            layout_hint="review-paper",
            tags=["physics", "optics"],
            content_format="latex",
            summary="A detailed review.",
            license_="CC-BY-SA-4.0",
        )

        resp = await client.get(f"/v1/entries/{entry['id']}")
        assert resp.status_code == 200
        data = resp.json()

        # All EntryResponse fields present
        assert data["id"] == entry["id"]
        assert data["title"] == "Detailed Entry"
        assert data["layout_hint"] == "review-paper"
        assert data["tags"] == ["physics", "optics"]
        assert data["content_format"] == "latex"
        assert data["summary"] == "A detailed review."
        assert data["license"] == "CC-BY-SA-4.0"
        assert data["schema_version"] == 1
        assert data["repo_name"] is not None
        assert data["repo_status"] == "provisioning"
        assert data["status"] == "active"
        assert data["created_by"] == agent["id"]
        assert data["created_at"] is not None
        assert data["updated_at"] is not None
        assert "forgejo_repo_id" in data
        assert "current_head_sha" in data

    async def test_get_entry_includes_content_cache(
        self, authed: AuthedFixture
    ) -> None:
        """Detail response DOES include content_cache (unlike list)."""
        client, _, token = authed
        entry = await _create_entry(client, token, title="Content Cache Entry")

        resp = await client.get(f"/v1/entries/{entry['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert "content_cache" in data

    async def test_get_entry_does_not_require_authentication(
        self, authed: AuthedFixture
    ) -> None:
        """GET /v1/entries/{id} is public, no auth header needed."""
        client, _, token = authed
        entry = await _create_entry(client, token, title="Public Detail Entry")

        # Request without auth
        resp = await client.get(f"/v1/entries/{entry['id']}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Public Detail Entry"


class TestGetEntryDetailWithRefs:
    """Scenario: Detail response includes outgoing_refs and incoming_refs."""

    async def test_entry_with_no_refs_returns_empty_ref_lists(
        self, authed: AuthedFixture
    ) -> None:
        """An entry with no refs returns outgoing_refs=[] and incoming_refs=[]."""
        client, _, token = authed
        entry = await _create_entry(client, token, title="No Refs Entry")

        resp = await client.get(f"/v1/entries/{entry['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["outgoing_refs"] == []
        assert data["incoming_refs"] == []

    async def test_entry_with_outgoing_refs(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Outgoing refs (from this entry to others) appear in outgoing_refs."""
        client, _, token = authed
        source = await _create_entry(client, token, title="Source Entry")
        target_a = await _create_entry(client, token, title="Target A")
        target_b = await _create_entry(client, token, title="Target B")

        ref_a = await _insert_entry_ref(
            e2e_session_factory,
            from_entry_id=source["id"],
            to_entry_id=target_a["id"],
            rel="cites",
            version_sha="abc123" + "0" * 34,
            note="Citation of Target A",
        )
        ref_b = await _insert_entry_ref(
            e2e_session_factory,
            from_entry_id=source["id"],
            to_entry_id=target_b["id"],
            rel="extends",
        )

        resp = await client.get(f"/v1/entries/{source['id']}")
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["outgoing_refs"]) == 2
        assert data["incoming_refs"] == []

        outgoing_ids = {r["id"] for r in data["outgoing_refs"]}
        assert ref_a["id"] in outgoing_ids
        assert ref_b["id"] in outgoing_ids

    async def test_entry_with_incoming_refs(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Incoming refs (from other entries to this one) appear in incoming_refs."""
        client, _, token = authed
        target = await _create_entry(client, token, title="Target Entry")
        source_a = await _create_entry(client, token, title="Source A")
        source_b = await _create_entry(client, token, title="Source B")

        ref_a = await _insert_entry_ref(
            e2e_session_factory,
            from_entry_id=source_a["id"],
            to_entry_id=target["id"],
            rel="evidence",
        )
        ref_b = await _insert_entry_ref(
            e2e_session_factory,
            from_entry_id=source_b["id"],
            to_entry_id=target["id"],
            rel="derives_from",
        )

        resp = await client.get(f"/v1/entries/{target['id']}")
        assert resp.status_code == 200
        data = resp.json()

        assert data["outgoing_refs"] == []
        assert len(data["incoming_refs"]) == 2

        incoming_ids = {r["id"] for r in data["incoming_refs"]}
        assert ref_a["id"] in incoming_ids
        assert ref_b["id"] in incoming_ids

    async def test_entry_with_both_outgoing_and_incoming_refs(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """An entry can have both outgoing and incoming refs simultaneously."""
        client, _, token = authed
        entry = await _create_entry(client, token, title="Hub Entry")
        source = await _create_entry(client, token, title="Source")
        target = await _create_entry(client, token, title="Target")

        outgoing_ref = await _insert_entry_ref(
            e2e_session_factory,
            from_entry_id=entry["id"],
            to_entry_id=target["id"],
            rel="cites",
        )
        incoming_ref = await _insert_entry_ref(
            e2e_session_factory,
            from_entry_id=source["id"],
            to_entry_id=entry["id"],
            rel="evidence",
        )

        resp = await client.get(f"/v1/entries/{entry['id']}")
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["outgoing_refs"]) == 1
        assert len(data["incoming_refs"]) == 1
        assert data["outgoing_refs"][0]["id"] == outgoing_ref["id"]
        assert data["incoming_refs"][0]["id"] == incoming_ref["id"]

    async def test_ref_response_shape(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Each ref in the response matches the EntryRefResponse schema."""
        client, _, token = authed
        entry_a = await _create_entry(client, token, title="Ref Shape Source")
        entry_b = await _create_entry(client, token, title="Ref Shape Target")

        sha = "deadbeef" + "0" * 32
        await _insert_entry_ref(
            e2e_session_factory,
            from_entry_id=entry_a["id"],
            to_entry_id=entry_b["id"],
            rel="evidence",
            version_sha=sha,
            note="This is supporting evidence.",
        )

        resp = await client.get(f"/v1/entries/{entry_a['id']}")
        assert resp.status_code == 200
        ref = resp.json()["outgoing_refs"][0]

        # All EntryRefResponse fields present with correct types
        assert "id" in ref
        UUID(ref["id"])  # valid UUID
        assert ref["from_entry_id"] == entry_a["id"]
        assert ref["to_entry_id"] == entry_b["id"]
        assert ref["rel"] == "evidence"
        assert ref["version_sha"] == sha
        assert ref["note"] == "This is supporting evidence."
        assert "created_at" in ref
        assert ref["created_at"] is not None

    async def test_outgoing_refs_not_mixed_into_incoming(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Outgoing refs must only appear in outgoing_refs, not incoming_refs."""
        client, _, token = authed
        entry_a = await _create_entry(client, token, title="Direction Source")
        entry_b = await _create_entry(client, token, title="Direction Target")

        await _insert_entry_ref(
            e2e_session_factory,
            from_entry_id=entry_a["id"],
            to_entry_id=entry_b["id"],
            rel="cites",
        )

        # Check from source perspective
        resp_a = await client.get(f"/v1/entries/{entry_a['id']}")
        data_a = resp_a.json()
        assert len(data_a["outgoing_refs"]) == 1
        assert len(data_a["incoming_refs"]) == 0
        assert data_a["outgoing_refs"][0]["from_entry_id"] == entry_a["id"]

        # Check from target perspective
        resp_b = await client.get(f"/v1/entries/{entry_b['id']}")
        data_b = resp_b.json()
        assert len(data_b["outgoing_refs"]) == 0
        assert len(data_b["incoming_refs"]) == 1
        assert data_b["incoming_refs"][0]["to_entry_id"] == entry_b["id"]

    async def test_all_refs_returned_not_capped(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """All refs are returned without a cap (no limit of 200 on detail refs)."""
        client, _, token = authed
        source = await _create_entry(client, token, title="Many Refs Source")

        # Create more targets than a typical limit would allow.
        # We use a smaller number than 200 for test speed, but enough to verify
        # there is no low artificial cap.
        target_ids = []
        for i in range(15):
            t = await _create_entry(client, token, title=f"Ref Target {i}")
            target_ids.append(t["id"])

        for tid in target_ids:
            await _insert_entry_ref(
                e2e_session_factory,
                from_entry_id=source["id"],
                to_entry_id=tid,
                rel="cites",
            )

        resp = await client.get(f"/v1/entries/{source['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["outgoing_refs"]) == 15


class TestGetEntryDetailErrors:
    """Scenario: Error responses for the detail endpoint."""

    async def test_nonexistent_uuid_returns_404(
        self, client: httpx.AsyncClient
    ) -> None:
        """GET with a valid UUID that does not exist returns 404."""
        fake_id = uuid4()
        resp = await client.get(f"/v1/entries/{fake_id}")
        assert resp.status_code == 404

    async def test_invalid_uuid_format_returns_422(
        self, client: httpx.AsyncClient
    ) -> None:
        """GET with an invalid UUID format returns 422."""
        resp = await client.get("/v1/entries/not-a-valid-uuid")
        assert resp.status_code == 422

    async def test_invalid_uuid_numeric_returns_422(
        self, client: httpx.AsyncClient
    ) -> None:
        """GET with a plain number instead of UUID returns 422."""
        resp = await client.get("/v1/entries/12345")
        assert resp.status_code == 422

    async def test_empty_path_param_returns_not_found_or_method(
        self, client: httpx.AsyncClient
    ) -> None:
        """GET /v1/entries/ (trailing slash, empty ID) is handled gracefully.

        This should either return 404/405 or redirect to the list endpoint,
        but must not return 500.
        """
        resp = await client.get("/v1/entries/")
        assert resp.status_code != 500


class TestListAndDetailConsistency:
    """Scenario: List and detail endpoints return consistent data for the same entry."""

    async def test_list_and_detail_fields_match(
        self, authed: AuthedFixture
    ) -> None:
        """Field values in list item match corresponding detail fields."""
        client, _, token = authed
        entry = await _create_entry(
            client,
            token,
            title="Consistency Check",
            layout_hint="law",
            tags=["consistency"],
            content_format="markdown",
            summary="Consistent summary.",
            license_="CC-BY-4.0",
        )

        list_resp = await client.get("/v1/entries")
        assert list_resp.status_code == 200
        list_items = list_resp.json()["items"]
        list_item = next(i for i in list_items if i["id"] == entry["id"])

        detail_resp = await client.get(f"/v1/entries/{entry['id']}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()

        # All shared fields must match
        for field in [
            "id", "title", "layout_hint", "tags", "summary", "license",
            "content_format", "schema_version", "forgejo_repo_id", "repo_name",
            "current_head_sha", "repo_status", "status", "created_by",
            "created_at", "updated_at",
        ]:
            assert list_item[field] == detail[field], (
                f"Mismatch on field '{field}': list={list_item[field]!r} "
                f"vs detail={detail[field]!r}"
            )

    async def test_detail_has_extra_fields_over_list(
        self, authed: AuthedFixture
    ) -> None:
        """Detail has content_cache, outgoing_refs, incoming_refs that list lacks."""
        client, _, token = authed
        entry = await _create_entry(client, token, title="Extra Fields")

        list_resp = await client.get("/v1/entries")
        list_item = next(
            i for i in list_resp.json()["items"] if i["id"] == entry["id"]
        )

        detail_resp = await client.get(f"/v1/entries/{entry['id']}")
        detail = detail_resp.json()

        # Detail has these; list does not
        assert "content_cache" in detail
        assert "outgoing_refs" in detail
        assert "incoming_refs" in detail
        assert "content_cache" not in list_item
        assert "outgoing_refs" not in list_item
        assert "incoming_refs" not in list_item
