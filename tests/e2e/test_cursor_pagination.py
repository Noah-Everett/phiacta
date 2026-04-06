# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for PHI-193: Universal Cursor-Based Pagination.

Tests the full HTTP contract for cursor-based pagination across all 14
list endpoints. Verifies:
- New CursorPage shape: {items, limit, has_more, next_cursor}
- No ``total`` or ``offset`` fields in any response
- Multi-page cursor chaining
- Invalid/malformed cursor returns 400
- Sort param mismatch with cursor returns 400
- Bounded endpoints always return has_more=false
- Empty collections return correct shape
- Different sort orders
- Edge cases (limit=1, exact-limit results)
"""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import phiacta.extensions.metadata.models  # noqa: F401
import phiacta.extensions.references.models  # noqa: F401
import phiacta.extensions.tags.models  # noqa: F401
import phiacta.extensions.types.models  # noqa: F401

from phiacta.core.services.git_service import AuthorInfo, CommitInfo
from tests.e2e.conftest import (
    FakeGitService,
    auth_header,
    create_entry,
    register_user,
    set_entry_repo_status,
    set_entry_visibility,
)

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cursor_page_shape(data: dict) -> None:
    """Assert that the response has the CursorPage shape and NOT the old shape."""
    assert "items" in data, "Missing 'items' key"
    assert "limit" in data, "Missing 'limit' key"
    assert "has_more" in data, "Missing 'has_more' key"
    assert "next_cursor" in data, "Missing 'next_cursor' key"
    # Old fields must NOT be present
    assert "total" not in data, "'total' field must not appear in CursorPage"
    assert "offset" not in data, "'offset' field must not appear in CursorPage"
    # Type checks
    assert isinstance(data["items"], list)
    assert isinstance(data["limit"], int)
    assert isinstance(data["has_more"], bool)
    assert data["next_cursor"] is None or isinstance(data["next_cursor"], str)


def _make_invalid_cursor() -> str:
    """Return a cursor that is not valid base64url-encoded JSON."""
    return "not-a-valid-cursor!!!"


def _make_cursor_bad_json() -> str:
    """Return a cursor that is valid base64url but invalid JSON."""
    return base64.urlsafe_b64encode(b"this is not json").decode().rstrip("=")


def _make_cursor_sort_mismatch() -> str:
    """Return a cursor with sort=updated_at to test against default created_at."""
    payload = json.dumps({"s": "updated_at", "o": "desc", "v": "2026-01-01T00:00:00", "id": str(uuid4())})
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mount_extension_routers(client: httpx.AsyncClient) -> None:
    """Mount extension and tool routers needed by pagination tests."""
    from phiacta.extensions.tags import router as tags_router
    from phiacta.extensions.references import router as refs_router
    from phiacta.tools.search.router import router as search_router
    from phiacta.main import app as _app

    _app.include_router(tags_router, prefix="/v1/extensions/tags", tags=["tags"])
    _app.include_router(refs_router, prefix="/v1/extensions/references", tags=["references"])
    _app.include_router(search_router, prefix="/v1/tools/search", tags=["search"])
    yield  # type: ignore[misc]
    prefixes = ("/v1/extensions/tags", "/v1/extensions/references", "/v1/tools/search")
    _app.routes[:] = [
        r for r in _app.routes
        if not (hasattr(r, "path") and any(r.path.startswith(p) for p in prefixes))
    ]


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    """Register a user and return (client, user_data, token)."""
    uid = uuid4().hex[:8]
    auth = await register_user(client, username=f"page-user-{uid}")
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def other_user(client: httpx.AsyncClient) -> AuthedFixture:
    """Register a second user for visibility tests."""
    uid = uuid4().hex[:8]
    auth = await register_user(client, username=f"page-other-{uid}")
    return client, auth["user"], auth["access_token"]


async def _create_ready_entry(
    client: httpx.AsyncClient,
    token: str,
    session_factory: async_sessionmaker[AsyncSession],
    title: str = "Pagination Test Entry",
) -> dict:
    """Create an entry and set it to repo_status='ready'."""
    entry = await create_entry(client, token, title=title)
    await set_entry_repo_status(session_factory, entry["id"], "ready")
    return entry


# ===========================================================================
# 1. Entries endpoint — keyset pagination
# ===========================================================================


class TestEntriesCursorPageShape:
    """Scenario: GET /v1/entries returns CursorPage[EntryListItem] shape."""

    async def test_entries_returns_cursor_page_shape(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /v1/entries returns the new CursorPage shape with items, limit,
        has_more, and next_cursor. No total, no offset."""
        client, _, token = authed
        await _create_ready_entry(client, token, e2e_session_factory, title="Shape Test")

        resp = await client.get("/v1/entries", headers=auth_header(token))
        assert resp.status_code == 200
        _cursor_page_shape(resp.json())

    async def test_entries_empty_returns_cursor_page_shape(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """Empty collection returns {items: [], has_more: false, next_cursor: null, limit: N}."""
        resp = await client.get("/v1/entries")
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)
        assert data["items"] == []
        assert data["has_more"] is False
        assert data["next_cursor"] is None

    async def test_entries_no_offset_query_param(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """The offset query param should be replaced by cursor. Sending offset
        should be rejected or ignored (endpoint no longer accepts it)."""
        resp = await client.get("/v1/entries", params={"offset": 10})
        # Implementation should either reject the unknown param or ignore it.
        # The key point: response must NOT contain 'offset' in the body.
        if resp.status_code == 200:
            data = resp.json()
            assert "offset" not in data
            _cursor_page_shape(data)


class TestEntriesMultiPagePagination:
    """Scenario: Paginate through entries using cursor chaining."""

    async def test_paginate_all_entries_with_cursor(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Create 5 entries, paginate with limit=2, collect all items via cursor
        chaining. Every entry must appear exactly once."""
        client, _, token = authed
        created_ids = []
        for i in range(5):
            entry = await _create_ready_entry(
                client, token, e2e_session_factory,
                title=f"Paginate Entry {i}",
            )
            created_ids.append(entry["id"])

        all_ids: list[str] = []
        cursor = None
        pages = 0
        max_pages = 10  # safety limit

        while pages < max_pages:
            params: dict = {"limit": 2}
            if cursor is not None:
                params["cursor"] = cursor
            resp = await client.get(
                "/v1/entries", params=params, headers=auth_header(token),
            )
            assert resp.status_code == 200
            data = resp.json()
            _cursor_page_shape(data)

            assert len(data["items"]) <= 2
            for item in data["items"]:
                all_ids.append(item["id"])

            pages += 1
            if not data["has_more"]:
                assert data["next_cursor"] is None
                break
            else:
                assert data["next_cursor"] is not None
                cursor = data["next_cursor"]

        # All created entries must appear exactly once
        for eid in created_ids:
            assert eid in all_ids, f"Entry {eid} missing from paginated results"
        # No duplicates
        assert len(all_ids) == len(set(all_ids)), "Duplicate entries in paginated results"

    async def test_first_page_no_cursor(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """First page (no cursor) returns items and a next_cursor if more exist."""
        client, _, token = authed
        for i in range(3):
            await _create_ready_entry(
                client, token, e2e_session_factory,
                title=f"First Page Entry {i}",
            )

        resp = await client.get(
            "/v1/entries", params={"limit": 2}, headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)
        assert len(data["items"]) == 2
        assert data["has_more"] is True
        assert data["next_cursor"] is not None

    async def test_last_page_has_more_false(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Last page has has_more=false and next_cursor=null."""
        client, _, token = authed
        await _create_ready_entry(client, token, e2e_session_factory, title="Solo")

        resp = await client.get(
            "/v1/entries", params={"limit": 50}, headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)
        assert data["has_more"] is False
        assert data["next_cursor"] is None

    async def test_limit_1_edge_case(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Paginating with limit=1 returns one item per page."""
        client, _, token = authed
        for i in range(3):
            await _create_ready_entry(
                client, token, e2e_session_factory,
                title=f"Limit1 Entry {i}",
            )

        cursor = None
        total_items = 0
        for _ in range(10):
            params: dict = {"limit": 1}
            if cursor:
                params["cursor"] = cursor
            resp = await client.get(
                "/v1/entries", params=params, headers=auth_header(token),
            )
            assert resp.status_code == 200
            data = resp.json()
            _cursor_page_shape(data)
            assert len(data["items"]) <= 1
            total_items += len(data["items"])
            if not data["has_more"]:
                break
            cursor = data["next_cursor"]

        assert total_items >= 3

    async def test_exact_limit_boundary(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """When there are exactly N items and limit=N, has_more should be false."""
        client, _, token = authed
        for i in range(3):
            await _create_ready_entry(
                client, token, e2e_session_factory,
                title=f"Exact Boundary {i}",
            )

        # Count how many entries this user can see
        resp = await client.get(
            "/v1/entries", params={"limit": 200}, headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        count = len(data["items"])

        # Now fetch with exactly that limit
        resp = await client.get(
            "/v1/entries", params={"limit": count}, headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)
        assert len(data["items"]) == count
        assert data["has_more"] is False
        assert data["next_cursor"] is None


class TestEntriesSortOrders:
    """Scenario: Different sort orders produce correct pagination."""

    async def test_sort_created_at_desc(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Entries sorted by created_at desc: newest first."""
        client, _, token = authed
        entries = []
        for i in range(3):
            e = await _create_ready_entry(
                client, token, e2e_session_factory,
                title=f"Sort Desc {i}",
            )
            entries.append(e)

        resp = await client.get(
            "/v1/entries",
            params={"sort": "created_at", "order": "desc", "limit": 50},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)
        items = data["items"]
        # Verify descending order
        for i in range(len(items) - 1):
            assert items[i]["created_at"] >= items[i + 1]["created_at"]

    async def test_sort_created_at_asc(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Entries sorted by created_at asc: oldest first."""
        client, _, token = authed
        for i in range(3):
            await _create_ready_entry(
                client, token, e2e_session_factory,
                title=f"Sort Asc {i}",
            )

        resp = await client.get(
            "/v1/entries",
            params={"sort": "created_at", "order": "asc", "limit": 50},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)
        items = data["items"]
        for i in range(len(items) - 1):
            assert items[i]["created_at"] <= items[i + 1]["created_at"]

    async def test_sort_updated_at_desc(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Entries sorted by updated_at desc."""
        client, _, token = authed
        for i in range(3):
            await _create_ready_entry(
                client, token, e2e_session_factory,
                title=f"Sort Updated {i}",
            )

        resp = await client.get(
            "/v1/entries",
            params={"sort": "updated_at", "order": "desc", "limit": 50},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)
        items = data["items"]
        for i in range(len(items) - 1):
            assert items[i]["updated_at"] >= items[i + 1]["updated_at"]


class TestEntriesInvalidCursor:
    """Scenario: Invalid or malformed cursors return 400."""

    async def test_invalid_cursor_returns_400(
        self,
        authed: AuthedFixture,
    ) -> None:
        """Passing a malformed cursor string returns 400."""
        client, _, token = authed
        resp = await client.get(
            "/v1/entries",
            params={"cursor": _make_invalid_cursor()},
            headers=auth_header(token),
        )
        assert resp.status_code == 400

    async def test_cursor_bad_json_returns_400(
        self,
        authed: AuthedFixture,
    ) -> None:
        """Cursor that is valid base64 but invalid JSON returns 400."""
        client, _, token = authed
        resp = await client.get(
            "/v1/entries",
            params={"cursor": _make_cursor_bad_json()},
            headers=auth_header(token),
        )
        assert resp.status_code == 400

    async def test_cursor_sort_mismatch_returns_400(
        self,
        authed: AuthedFixture,
    ) -> None:
        """Cursor encoded with sort=updated_at but query has sort=created_at returns 400."""
        client, _, token = authed
        resp = await client.get(
            "/v1/entries",
            params={
                "cursor": _make_cursor_sort_mismatch(),
                "sort": "created_at",
                "order": "desc",
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 400


# ===========================================================================
# 2. Activity endpoint — keyset pagination
# ===========================================================================


class TestActivityCursorPage:
    """Scenario: GET /v1/activity returns CursorPage[ActivityItem] shape."""

    async def test_activity_returns_cursor_page_shape(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Activity feed returns the CursorPage shape after creating entries
        that generate activity events."""
        client, user, token = authed
        await _create_ready_entry(
            client, token, e2e_session_factory, title="Activity Shape"
        )

        resp = await client.get("/v1/activity", params={"actor": user["id"]})
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)

    async def test_activity_empty_returns_cursor_page_shape(
        self,
        authed: AuthedFixture,
    ) -> None:
        """Empty activity feed returns correct CursorPage shape."""
        client, user, _ = authed
        resp = await client.get("/v1/activity", params={"actor": user["id"]})
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)
        assert data["items"] == []
        assert data["has_more"] is False
        assert data["next_cursor"] is None

    async def test_activity_pagination_with_cursor(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Create multiple entries to generate activity events, then paginate
        through them with limit=1."""
        client, user, token = authed
        for i in range(3):
            await _create_ready_entry(
                client, token, e2e_session_factory,
                title=f"Activity Page {i}",
            )

        all_ids: list[str] = []
        cursor = None
        for _ in range(10):
            params: dict = {"actor": user["id"], "limit": 1}
            if cursor:
                params["cursor"] = cursor
            resp = await client.get("/v1/activity", params=params)
            assert resp.status_code == 200
            data = resp.json()
            _cursor_page_shape(data)
            for item in data["items"]:
                all_ids.append(item["id"])
            if not data["has_more"]:
                break
            cursor = data["next_cursor"]

        # Should have at least 3 activity items (entry.created events)
        assert len(all_ids) >= 3
        # No duplicates
        assert len(all_ids) == len(set(all_ids))

    async def test_activity_visibility_filters_private_entries(
        self,
        authed: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Activity items for private entries are filtered out for non-owners.
        The pagination still returns the correct CursorPage shape."""
        client, owner_data, owner_token = authed
        _, _, other_token = other_user

        # Create a public entry then a private one
        public_entry = await _create_ready_entry(
            client, owner_token, e2e_session_factory, title="Public Activity"
        )
        private_entry = await _create_ready_entry(
            client, owner_token, e2e_session_factory, title="Private Activity"
        )
        await set_entry_visibility(
            e2e_session_factory, private_entry["id"], "private"
        )

        # Non-owner fetches owner's activity
        resp = await client.get(
            "/v1/activity",
            params={"actor": owner_data["id"]},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)

        # Private entry activity should be filtered out
        entity_ids = [item["entity_id"] for item in data["items"]]
        assert private_entry["id"] not in entity_ids

    async def test_activity_invalid_cursor_returns_400(
        self,
        authed: AuthedFixture,
    ) -> None:
        """Invalid cursor on activity endpoint returns 400."""
        client, user, _ = authed
        resp = await client.get(
            "/v1/activity",
            params={"actor": user["id"], "cursor": _make_invalid_cursor()},
        )
        assert resp.status_code == 400


# ===========================================================================
# 3. Forgejo-proxied endpoints — page-encoded cursors
# ===========================================================================


class TestEditsCursorPage:
    """Scenario: GET /v1/entries/{id}/edits returns CursorPage shape."""

    async def test_edits_returns_cursor_page_shape(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """List edit proposals returns CursorPage shape."""
        client, _, token = authed
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="Edits Shape"
        )

        resp = await client.get(
            f"/v1/entries/{entry['id']}/edits",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)

    async def test_edits_empty_returns_cursor_page_shape(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """Empty edits list returns correct CursorPage shape."""
        client, _, token = authed
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="No Edits"
        )

        resp = await client.get(
            f"/v1/entries/{entry['id']}/edits",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)
        assert data["items"] == []
        assert data["has_more"] is False
        assert data["next_cursor"] is None

    async def test_edits_pagination_with_multiple_proposals(
        self,
        authed: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """Create multiple edit proposals and paginate through them."""
        client, _, owner_token = authed
        _, _, other_token = other_user
        entry = await _create_ready_entry(
            client, owner_token, e2e_session_factory, title="Edits Paginate"
        )
        entry_id = entry["id"]

        # Create 3 edit proposals
        for i in range(3):
            await client.post(
                f"/v1/entries/{entry_id}/edits",
                json={
                    "title": f"Edit proposal {i}",
                    "files": [{"path": f"file{i}.md", "content": f"content {i}"}],
                },
                headers=auth_header(other_token),
            )

        # Paginate with limit=1
        all_items: list[dict] = []
        cursor = None
        for _ in range(10):
            params: dict = {"limit": 1}
            if cursor:
                params["cursor"] = cursor
            resp = await client.get(
                f"/v1/entries/{entry_id}/edits",
                params=params,
                headers=auth_header(owner_token),
            )
            assert resp.status_code == 200
            data = resp.json()
            _cursor_page_shape(data)
            all_items.extend(data["items"])
            if not data["has_more"]:
                break
            cursor = data["next_cursor"]

        assert len(all_items) >= 3

    async def test_edits_invalid_cursor_returns_400(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """Invalid cursor on edits endpoint returns 400."""
        client, _, token = authed
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="Edits Bad Cursor"
        )

        resp = await client.get(
            f"/v1/entries/{entry['id']}/edits",
            params={"cursor": _make_invalid_cursor()},
            headers=auth_header(token),
        )
        assert resp.status_code == 400


class TestIssuesCursorPage:
    """Scenario: GET /v1/entries/{id}/issues returns CursorPage shape."""

    async def test_issues_returns_cursor_page_shape(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """List issues returns CursorPage shape."""
        client, _, token = authed
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="Issues Shape"
        )

        resp = await client.get(
            f"/v1/entries/{entry['id']}/issues",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)

    async def test_issues_empty_returns_cursor_page_shape(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """Empty issues list returns correct CursorPage shape."""
        client, _, token = authed
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="No Issues"
        )

        resp = await client.get(
            f"/v1/entries/{entry['id']}/issues",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)
        assert data["items"] == []
        assert data["has_more"] is False
        assert data["next_cursor"] is None

    async def test_issues_pagination_with_cursor(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """Create multiple issues and paginate through them."""
        client, _, token = authed
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="Issues Paginate"
        )
        entry_id = entry["id"]

        for i in range(3):
            await client.post(
                f"/v1/entries/{entry_id}/issues",
                json={"title": f"Issue {i}", "body": f"Body {i}"},
                headers=auth_header(token),
            )

        # Paginate with limit=1
        all_items: list[dict] = []
        cursor = None
        for _ in range(10):
            params: dict = {"limit": 1}
            if cursor:
                params["cursor"] = cursor
            resp = await client.get(
                f"/v1/entries/{entry_id}/issues",
                params=params,
                headers=auth_header(token),
            )
            assert resp.status_code == 200
            data = resp.json()
            _cursor_page_shape(data)
            all_items.extend(data["items"])
            if not data["has_more"]:
                break
            cursor = data["next_cursor"]

        assert len(all_items) >= 3

    async def test_issues_invalid_cursor_returns_400(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """Invalid cursor on issues endpoint returns 400."""
        client, _, token = authed
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="Issues Bad Cursor"
        )

        resp = await client.get(
            f"/v1/entries/{entry['id']}/issues",
            params={"cursor": _make_invalid_cursor()},
            headers=auth_header(token),
        )
        assert resp.status_code == 400


class TestHistoryCursorPage:
    """Scenario: GET /v1/entries/{id}/history returns CursorPage shape."""

    async def test_history_returns_cursor_page_shape(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """List commits returns CursorPage shape."""
        client, _, token = authed
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="History Shape"
        )
        entry_id = entry["id"]

        # Populate commit history in fake git
        eid = UUID(entry_id)
        ts = datetime(2026, 3, 20, 12, 0, 0, tzinfo=UTC)
        fake_git.commit_history[eid] = [
            CommitInfo(
                sha="a" * 40,
                message="Initial commit",
                author=AuthorInfo(name="test", email="test@phiacta.local"),
                timestamp=ts,
            ),
        ]

        resp = await client.get(
            f"/v1/entries/{entry_id}/history",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)

    async def test_history_empty_returns_cursor_page_shape(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """Empty commit history returns correct CursorPage shape."""
        client, _, token = authed
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="No History"
        )

        resp = await client.get(
            f"/v1/entries/{entry['id']}/history",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)
        assert data["items"] == []
        assert data["has_more"] is False
        assert data["next_cursor"] is None

    async def test_history_invalid_cursor_returns_400(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """Invalid cursor on history endpoint returns 400."""
        client, _, token = authed
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="History Bad Cursor"
        )

        resp = await client.get(
            f"/v1/entries/{entry['id']}/history",
            params={"cursor": _make_invalid_cursor()},
            headers=auth_header(token),
        )
        assert resp.status_code == 400


# ===========================================================================
# 4. Bounded endpoints — always has_more=false
# ===========================================================================


class TestFilesBoundedCursorPage:
    """Scenario: GET /v1/entries/{id}/files is bounded, always has_more=false."""

    async def test_files_returns_cursor_page_shape(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """List files returns CursorPage with has_more=false."""
        client, _, token = authed
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="Files Shape"
        )
        eid = UUID(entry["id"])
        fake_git.files[(eid, "README.md")] = b"hello"
        fake_git.files[(eid, "data.csv")] = b"a,b,c"

        resp = await client.get(
            f"/v1/entries/{entry['id']}/files",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)
        assert data["has_more"] is False
        assert data["next_cursor"] is None
        assert len(data["items"]) >= 2

    async def test_files_empty_returns_cursor_page_shape(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """Empty file list returns correct bounded CursorPage shape."""
        client, _, token = authed
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="No Files"
        )

        resp = await client.get(
            f"/v1/entries/{entry['id']}/files",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)
        assert data["has_more"] is False
        assert data["next_cursor"] is None


class TestPluginsBoundedCursorPage:
    """Scenario: GET /v1/plugins is bounded, always has_more=false."""

    async def test_plugins_returns_cursor_page_shape(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """List plugins returns CursorPage with has_more=false."""
        resp = await client.get("/v1/plugins")
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)
        assert data["has_more"] is False
        assert data["next_cursor"] is None


class TestDocsBoundedCursorPage:
    """Scenario: GET /v1/docs is bounded, always has_more=false."""

    async def test_docs_returns_cursor_page_shape(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """List docs returns CursorPage with has_more=false."""
        resp = await client.get("/v1/docs")
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)
        assert data["has_more"] is False
        assert data["next_cursor"] is None


class TestTokensBoundedCursorPage:
    """Scenario: GET /v1/auth/tokens is bounded, always has_more=false."""

    async def test_tokens_returns_cursor_page_shape(
        self,
        authed: AuthedFixture,
    ) -> None:
        """List tokens returns CursorPage with has_more=false."""
        client, _, token = authed
        resp = await client.get(
            "/v1/auth/tokens",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)
        assert data["has_more"] is False
        assert data["next_cursor"] is None

    async def test_tokens_with_items_still_bounded(
        self,
        authed: AuthedFixture,
    ) -> None:
        """Even with tokens present, has_more is always false."""
        client, _, token = authed

        # Create a PAT
        resp = await client.post(
            "/v1/auth/tokens",
            json={"name": "test-pat"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201

        resp = await client.get(
            "/v1/auth/tokens",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)
        assert data["has_more"] is False
        assert data["next_cursor"] is None
        assert len(data["items"]) >= 1


# ===========================================================================
# 5. Tags/entries endpoint — keyset pagination
# ===========================================================================


class TestTagsEntriesCursorPage:
    """Scenario: GET /v1/extensions/tags/entries returns CursorPage shape."""

    async def test_tags_entries_returns_cursor_page_shape(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Find entries by tags returns CursorPage shape."""
        client, _, token = authed
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="Tagged Entry"
        )
        entry_id = entry["id"]

        # Set tags
        await client.put(
            f"/v1/extensions/tags/{entry_id}",
            json={"tags": ["physics"]},
            headers=auth_header(token),
        )

        resp = await client.get(
            "/v1/extensions/tags/entries",
            params={"tags": "physics"},
        )
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)

    async def test_tags_entries_empty_returns_cursor_page_shape(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """Empty tag search returns correct CursorPage shape."""
        resp = await client.get(
            "/v1/extensions/tags/entries",
            params={"tags": "nonexistent-tag-xyzzy"},
        )
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)
        assert data["items"] == []
        assert data["has_more"] is False
        assert data["next_cursor"] is None

    async def test_tags_entries_pagination(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Create multiple tagged entries and paginate with limit=1."""
        client, _, token = authed
        for i in range(3):
            entry = await _create_ready_entry(
                client, token, e2e_session_factory,
                title=f"Tagged Paginate {i}",
            )
            await client.put(
                f"/v1/extensions/tags/{entry['id']}",
                json={"tags": ["paginate-test"]},
                headers=auth_header(token),
            )

        all_items: list[dict] = []
        cursor = None
        for _ in range(10):
            params: dict = {"tags": "paginate-test", "limit": 1}
            if cursor:
                params["cursor"] = cursor
            resp = await client.get(
                "/v1/extensions/tags/entries", params=params,
            )
            assert resp.status_code == 200
            data = resp.json()
            _cursor_page_shape(data)
            all_items.extend(data["items"])
            if not data["has_more"]:
                break
            cursor = data["next_cursor"]

        assert len(all_items) >= 3

    async def test_tags_entries_invalid_cursor_returns_400(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """Invalid cursor on tags/entries endpoint returns 400."""
        resp = await client.get(
            "/v1/extensions/tags/entries",
            params={"tags": "test", "cursor": _make_invalid_cursor()},
        )
        assert resp.status_code == 400


# ===========================================================================
# 6. References endpoint — keyset pagination
# ===========================================================================


class TestReferencesCursorPage:
    """Scenario: GET /v1/extensions/references/ returns CursorPage shape."""

    async def test_references_returns_cursor_page_shape(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """List references returns CursorPage shape."""
        client, _, token = authed
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="Refs Shape"
        )

        resp = await client.get(
            "/v1/extensions/references/",
            params={"entry_id": entry["id"]},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)

    async def test_references_empty_returns_cursor_page_shape(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Empty references list returns correct CursorPage shape."""
        client, _, token = authed
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="No Refs"
        )

        resp = await client.get(
            "/v1/extensions/references/",
            params={"entry_id": entry["id"]},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)
        assert data["items"] == []
        assert data["has_more"] is False
        assert data["next_cursor"] is None

    async def test_references_pagination(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Create multiple references and paginate through them."""
        client, _, token = authed
        source = await _create_ready_entry(
            client, token, e2e_session_factory, title="Source Entry"
        )
        targets = []
        for i in range(3):
            t = await _create_ready_entry(
                client, token, e2e_session_factory,
                title=f"Target {i}",
            )
            targets.append(t)

        # Create references
        for t in targets:
            resp = await client.post(
                f"/v1/extensions/references/{source['id']}",
                json={"target_entry_id": t["id"], "rel": "cites"},
                headers=auth_header(token),
            )
            assert resp.status_code == 201

        # Paginate with limit=1
        all_items: list[dict] = []
        cursor = None
        for _ in range(10):
            params: dict = {
                "entry_id": source["id"],
                "direction": "outgoing",
                "limit": 1,
            }
            if cursor:
                params["cursor"] = cursor
            resp = await client.get(
                "/v1/extensions/references/",
                params=params,
                headers=auth_header(token),
            )
            assert resp.status_code == 200
            data = resp.json()
            _cursor_page_shape(data)
            all_items.extend(data["items"])
            if not data["has_more"]:
                break
            cursor = data["next_cursor"]

        assert len(all_items) >= 3

    async def test_references_invalid_cursor_returns_400(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Invalid cursor on references endpoint returns 400."""
        client, _, token = authed
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="Refs Bad Cursor"
        )

        resp = await client.get(
            "/v1/extensions/references/",
            params={
                "entry_id": entry["id"],
                "cursor": _make_invalid_cursor(),
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 400


# ===========================================================================
# 7. Search endpoint — offset-based cursor
# ===========================================================================


class TestSearchCursorPage:
    """Scenario: GET /v1/tools/search/ returns CursorPage[SearchResultItem]
    shape with extra version_id field."""

    async def test_search_returns_cursor_page_shape(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Search returns the CursorPage shape (with version_id)."""
        client, _, token = authed
        await _create_ready_entry(
            client, token, e2e_session_factory, title="Search Shape Test"
        )

        resp = await client.get("/v1/tools/search/", params={"q": "search"})
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)
        # SearchResponse extends CursorPage with version_id
        assert "version_id" in data

    async def test_search_empty_returns_cursor_page_shape(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """Empty search returns correct CursorPage shape."""
        resp = await client.get(
            "/v1/tools/search/",
            params={"q": "nonexistent-term-xyzzy-12345"},
        )
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)
        assert data["items"] == []
        assert data["has_more"] is False
        assert data["next_cursor"] is None

    async def test_search_no_total_in_response(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """Search response must not include 'total' field."""
        resp = await client.get(
            "/v1/tools/search/",
            params={"q": "anything"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total" not in data

    async def test_search_no_offset_in_response(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """Search response must not include 'offset' field."""
        resp = await client.get(
            "/v1/tools/search/",
            params={"q": "anything"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "offset" not in data

    async def test_search_invalid_cursor_returns_400(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """Invalid cursor on search endpoint returns 400."""
        resp = await client.get(
            "/v1/tools/search/",
            params={"q": "test", "cursor": _make_invalid_cursor()},
        )
        assert resp.status_code == 400


# ===========================================================================
# 8. Cross-cutting: cursor is opaque
# ===========================================================================


class TestCursorOpaqueness:
    """Scenario: Clients treat the cursor as an opaque string.
    The cursor encodes internal state that must not be relied on externally."""

    async def test_cursor_is_non_empty_string(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """When has_more=true, next_cursor is a non-empty string."""
        client, _, token = authed
        for i in range(3):
            await _create_ready_entry(
                client, token, e2e_session_factory,
                title=f"Opaque Cursor {i}",
            )

        resp = await client.get(
            "/v1/entries",
            params={"limit": 1},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        if data["has_more"]:
            assert isinstance(data["next_cursor"], str)
            assert len(data["next_cursor"]) > 0

    async def test_page_cursor_rejected_by_keyset_endpoint(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """A page-encoded cursor (from Forgejo endpoints) should be rejected
        by a keyset endpoint (entries) because the cursor structure differs."""
        client, _, token = authed
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="Cross Cursor Test"
        )

        # Forge a page-encoded cursor (Forgejo style)
        page_cursor = base64.urlsafe_b64encode(
            json.dumps({"p": 2}).encode()
        ).decode().rstrip("=")

        # Use it on entries (keyset endpoint) — should fail
        resp = await client.get(
            "/v1/entries",
            params={"cursor": page_cursor},
            headers=auth_header(token),
        )
        # Should be 400 because the cursor is missing keyset fields (s, o, v, id)
        assert resp.status_code == 400


# ===========================================================================
# 9. Regression: existing functionality preserved
# ===========================================================================


class TestPaginationRegression:
    """Scenario: Pagination changes must not break existing entry operations."""

    async def test_entry_creation_still_works(
        self,
        authed: AuthedFixture,
    ) -> None:
        """POST /v1/entries still returns the expected entry response."""
        client, user, token = authed
        resp = await client.post(
            "/v1/entries",
            json={"title": "Regression Entry", "content_format": "markdown"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Regression Entry"
        assert data["created_by"] == user["id"]

    async def test_entry_get_still_works(
        self,
        authed: AuthedFixture,
    ) -> None:
        """GET /v1/entries/{id} still returns a single entry (not paginated)."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Still Fetchable")

        resp = await client.get(f"/v1/entries/{entry['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == entry["id"]
        assert data["title"] == "Still Fetchable"
        # Single entry GET should NOT be paginated
        assert "has_more" not in data
        assert "next_cursor" not in data

    async def test_limit_param_still_controls_page_size(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """The limit query param controls page size in the new response."""
        client, _, token = authed
        for i in range(5):
            await _create_ready_entry(
                client, token, e2e_session_factory,
                title=f"Limit Control {i}",
            )

        resp = await client.get(
            "/v1/entries",
            params={"limit": 3},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        _cursor_page_shape(data)
        assert len(data["items"]) <= 3
        assert data["limit"] == 3
