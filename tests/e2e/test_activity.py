# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for the Activity Feed endpoint.

Tests the full API contract for:
- GET /v1/activity?actor={user_id}  -- cursor-based paginated activity feed

The activity feed is the primary user-facing API for the entity registry.
It returns actions performed by a user in reverse chronological order.
"""

from __future__ import annotations

import base64
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.e2e.conftest import (
    FakeGitService,
    auth_header,
    create_entry,
    register_user,
    set_entry_repo_status,
)

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


@pytest.fixture
async def owner(client: httpx.AsyncClient) -> AuthedFixture:
    uid = uuid4().hex[:8]
    auth = await register_user(client, handle=f"activity-owner-{uid}")
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def other_user(client: httpx.AsyncClient) -> AuthedFixture:
    uid = uuid4().hex[:8]
    auth = await register_user(client, handle=f"activity-other-{uid}")
    return client, auth["user"], auth["access_token"]


async def _create_ready_entry(
    client: httpx.AsyncClient,
    token: str,
    session_factory: async_sessionmaker[AsyncSession],
    title: str = "Activity Test Entry",
) -> dict:
    entry = await create_entry(client, token, title=title)
    await set_entry_repo_status(session_factory, entry["id"], "ready")
    return entry


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------


class TestActivityResponseShape:
    """Scenario: Activity feed response has the correct structure."""

    async def test_response_has_items_and_next_cursor(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Response body has 'items' (list) and 'next_cursor' (UUID or null)."""
        client, user, token = owner
        await _create_ready_entry(client, token, e2e_session_factory)

        resp = await client.get("/v1/activity", params={"actor": user["id"]})
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert isinstance(data["items"], list)
        assert "next_cursor" in data

    async def test_activity_item_has_required_fields(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Each ActivityItem has: id, action, entity_type, entity_id,
        parent_id, metadata, created_at."""
        client, user, token = owner
        await _create_ready_entry(
            client, token, e2e_session_factory, title="Shape Test"
        )

        resp = await client.get("/v1/activity", params={"actor": user["id"]})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 1

        item = items[0]
        required_fields = {
            "id", "action", "entity_type", "entity_id",
            "parent_id", "metadata", "created_at",
        }
        assert required_fields.issubset(set(item.keys())), (
            f"Missing fields: {required_fields - set(item.keys())}"
        )

    async def test_activity_item_id_is_uuid(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Activity item 'id' is a valid UUID string."""
        client, user, token = owner
        await _create_ready_entry(client, token, e2e_session_factory)

        resp = await client.get("/v1/activity", params={"actor": user["id"]})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 1
        # Should not raise ValueError
        UUID(items[0]["id"])

    async def test_activity_item_entity_id_is_uuid(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Activity item 'entity_id' is a valid UUID string."""
        client, user, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)

        resp = await client.get("/v1/activity", params={"actor": user["id"]})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 1
        UUID(items[0]["entity_id"])


# ---------------------------------------------------------------------------
# Empty feed
# ---------------------------------------------------------------------------


class TestEmptyActivityFeed:
    """Scenario: User with no activity."""

    async def test_empty_feed_returns_empty_items(
        self, client: httpx.AsyncClient,
    ) -> None:
        """A newly registered user has no activity items."""
        auth = await register_user(client, handle="empty-feed-user")
        user_id = auth["user"]["id"]

        resp = await client.get("/v1/activity", params={"actor": user_id})
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["next_cursor"] is None

    async def test_empty_feed_is_public(
        self, client: httpx.AsyncClient,
    ) -> None:
        """Activity feed is accessible without authentication."""
        auth = await register_user(client, handle="public-feed-user")
        user_id = auth["user"]["id"]

        # No Authorization header
        resp = await client.get("/v1/activity", params={"actor": user_id})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestActivityFeedErrors:
    """Scenario: Error responses for the activity feed endpoint."""

    async def test_nonexistent_user_returns_404(
        self, client: httpx.AsyncClient,
    ) -> None:
        """GET /v1/activity?actor={nonexistent_uuid} returns 404."""
        fake_id = uuid4()
        resp = await client.get("/v1/activity", params={"actor": str(fake_id)})
        assert resp.status_code == 404

    async def test_invalid_uuid_returns_422(
        self, client: httpx.AsyncClient,
    ) -> None:
        """GET /v1/activity?actor=not-a-valid-uuid returns 422."""
        resp = await client.get("/v1/activity", params={"actor": "not-a-valid-uuid"})
        assert resp.status_code == 422

    async def test_limit_exceeds_max_returns_422_or_clamped(
        self,
        owner: AuthedFixture,
    ) -> None:
        """Requesting limit > 100 either returns 422 or is clamped to 100."""
        client, user, token = owner
        resp = await client.get(
            "/v1/activity",
            params={"actor": user["id"], "limit": 200},
        )
        # Either 422 (rejected) or 200 (clamped)
        assert resp.status_code in (200, 422)
        if resp.status_code == 200:
            # If clamped, items should not exceed 100
            assert len(resp.json()["items"]) <= 100

    async def test_invalid_before_cursor_returns_422(
        self,
        owner: AuthedFixture,
    ) -> None:
        """Providing a non-UUID 'before' cursor returns 422."""
        client, user, _ = owner
        resp = await client.get(
            "/v1/activity",
            params={"actor": user["id"], "before": "not-a-uuid"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


class TestActivityFeedOrdering:
    """Scenario: Activity events are returned in reverse chronological order."""

    async def test_reverse_chronological_order(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Multiple entry creations appear newest-first in the activity feed."""
        client, user, token = owner
        titles = ["First Entry", "Second Entry", "Third Entry"]
        for title in titles:
            await _create_ready_entry(
                client, token, e2e_session_factory, title=title
            )

        resp = await client.get("/v1/activity", params={"actor": user["id"]})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 3

        # All items should have created_at in descending order
        timestamps = [item["created_at"] for item in items]
        assert timestamps == sorted(timestamps, reverse=True), (
            "Activity items are not in reverse chronological order"
        )

    async def test_mixed_actions_are_still_chronologically_ordered(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """A mix of entry.created, issue.created, etc. are all ordered by
        created_at descending."""
        client, user, token = owner

        # Create entry
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="Mixed Actions"
        )
        entry_id = entry["id"]

        # Create issue
        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "An issue", "body": "Details"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201

        # Create second entry
        await _create_ready_entry(
            client, token, e2e_session_factory, title="Another Entry"
        )

        resp = await client.get("/v1/activity", params={"actor": user["id"]})
        assert resp.status_code == 200
        items = resp.json()["items"]
        timestamps = [item["created_at"] for item in items]
        assert timestamps == sorted(timestamps, reverse=True)


# ---------------------------------------------------------------------------
# Cursor pagination
# ---------------------------------------------------------------------------


class TestActivityFeedPagination:
    """Scenario: Cursor-based pagination works correctly."""

    async def test_default_limit(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Without limit param, default of 50 items is used."""
        client, user, token = owner
        # Create 3 entries -- should be well under default limit
        for i in range(3):
            await _create_ready_entry(
                client, token, e2e_session_factory, title=f"Default Limit {i}"
            )

        resp = await client.get("/v1/activity", params={"actor": user["id"]})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 3
        # With only 3 items, no next page
        assert data["next_cursor"] is None

    async def test_limit_parameter_respected(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Setting limit=2 returns at most 2 items."""
        client, user, token = owner
        for i in range(5):
            await _create_ready_entry(
                client, token, e2e_session_factory, title=f"Limit Test {i}"
            )

        resp = await client.get(
            "/v1/activity",
            params={"actor": user["id"], "limit": 2},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        # More items exist, so next_cursor should be set
        assert data["next_cursor"] is not None

    async def test_cursor_fetches_next_page(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Using next_cursor from page 1 as 'before' param returns page 2."""
        client, user, token = owner
        for i in range(5):
            await _create_ready_entry(
                client, token, e2e_session_factory, title=f"Cursor Test {i}"
            )

        # Page 1
        resp = await client.get(
            "/v1/activity",
            params={"actor": user["id"], "limit": 2},
        )
        assert resp.status_code == 200
        page1 = resp.json()
        assert len(page1["items"]) == 2
        cursor = page1["next_cursor"]
        assert cursor is not None

        # Page 2
        resp = await client.get(
            "/v1/activity",
            params={"actor": user["id"], "limit": 2, "before": cursor},
        )
        assert resp.status_code == 200
        page2 = resp.json()
        assert len(page2["items"]) == 2

        # No overlap between pages
        page1_ids = {item["id"] for item in page1["items"]}
        page2_ids = {item["id"] for item in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids), (
            "Cursor pagination returned overlapping items"
        )

    async def test_cursor_pagination_exhausts_all_items(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Paginating through all items with limit=2 collects all events."""
        client, user, token = owner
        for i in range(5):
            await _create_ready_entry(
                client, token, e2e_session_factory, title=f"Exhaust {i}"
            )

        all_items: list[dict] = []
        cursor = None
        for _ in range(10):  # Safety limit
            params: dict = {"actor": user["id"], "limit": 2}
            if cursor:
                params["before"] = cursor
            resp = await client.get(
                "/v1/activity",
                params=params,
            )
            assert resp.status_code == 200
            data = resp.json()
            all_items.extend(data["items"])
            cursor = data["next_cursor"]
            if cursor is None:
                break

        assert len(all_items) == 5
        # All IDs should be unique
        all_ids = [item["id"] for item in all_items]
        assert len(set(all_ids)) == 5

    async def test_last_page_has_null_cursor(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """The last page of results has next_cursor=null."""
        client, user, token = owner
        for i in range(3):
            await _create_ready_entry(
                client, token, e2e_session_factory, title=f"Last Page {i}"
            )

        # Fetch with limit larger than total
        resp = await client.get(
            "/v1/activity",
            params={"actor": user["id"], "limit": 50},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 3
        assert data["next_cursor"] is None


# ---------------------------------------------------------------------------
# Activity metadata
# ---------------------------------------------------------------------------


class TestActivityMetadata:
    """Scenario: Activity events contain correct metadata fields."""

    async def test_issue_created_metadata_has_title_and_entry_title(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """'issue.created' metadata includes issue title and entry_title."""
        client, user, token = owner
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="Metadata Parent Entry"
        )
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Data inconsistency", "body": "See section 3"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201

        resp = await client.get("/v1/activity", params={"actor": user["id"]})
        assert resp.status_code == 200
        items = resp.json()["items"]
        issue_events = [a for a in items if a["action"] == "issue.created"]
        assert len(issue_events) >= 1

        metadata = issue_events[0]["metadata"]
        assert metadata is not None
        assert "title" in metadata
        assert metadata["title"] == "Data inconsistency"
        # entry_title removed from activity metadata after entry minimization

    async def test_entry_created_activity_has_entity_type_entry(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """'entry.created' events have entity_type='entry'."""
        client, user, token = owner
        await _create_ready_entry(client, token, e2e_session_factory)

        resp = await client.get("/v1/activity", params={"actor": user["id"]})
        assert resp.status_code == 200
        items = resp.json()["items"]
        entry_events = [a for a in items if a["action"] == "entry.created"]
        assert len(entry_events) >= 1
        assert entry_events[0]["entity_type"] == "entry"

    async def test_entry_created_activity_has_null_parent_id(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Entries have no parent, so parent_id should be null."""
        client, user, token = owner
        await _create_ready_entry(
            client, token, e2e_session_factory, title="No Parent"
        )

        resp = await client.get("/v1/activity", params={"actor": user["id"]})
        assert resp.status_code == 200
        items = resp.json()["items"]
        entry_events = [a for a in items if a["action"] == "entry.created"]
        assert len(entry_events) >= 1
        assert entry_events[0]["parent_id"] is None


# ---------------------------------------------------------------------------
# User isolation
# ---------------------------------------------------------------------------


class TestActivityFeedIsolation:
    """Scenario: Activity feeds are isolated between users -- user A does
    not see user B's activity."""

    async def test_user_a_does_not_see_user_b_activity(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """User A's activity feed only contains user A's actions."""
        client, user_a, token_a = owner
        _, user_b, token_b = other_user

        # User A creates an entry
        entry_a = await _create_ready_entry(
            client, token_a, e2e_session_factory, title="User A's Entry"
        )
        # User B creates an entry
        entry_b = await _create_ready_entry(
            client, token_b, e2e_session_factory, title="User B's Entry"
        )

        # User A's feed
        resp = await client.get("/v1/activity", params={"actor": user_a["id"]})
        assert resp.status_code == 200
        a_items = resp.json()["items"]
        a_entity_ids = {item["entity_id"] for item in a_items}
        assert entry_a["id"] in a_entity_ids
        assert entry_b["id"] not in a_entity_ids

        # User B's feed
        resp = await client.get("/v1/activity", params={"actor": user_b["id"]})
        assert resp.status_code == 200
        b_items = resp.json()["items"]
        b_entity_ids = {item["entity_id"] for item in b_items}
        assert entry_b["id"] in b_entity_ids
        assert entry_a["id"] not in b_entity_ids

    async def test_issue_by_other_user_appears_in_their_feed(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """When user B creates an issue on user A's entry, the 'issue.created'
        event appears in user B's feed, not user A's."""
        client, user_a, token_a = owner
        _, user_b, token_b = other_user

        entry = await _create_ready_entry(
            client, token_a, e2e_session_factory, title="A's Entry"
        )
        entry_id = entry["id"]

        # User B creates an issue on A's entry
        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Spotted an error", "body": "In line 42"},
            headers=auth_header(token_b),
        )
        assert resp.status_code == 201

        # User B's feed should have the issue.created
        resp = await client.get("/v1/activity", params={"actor": user_b["id"]})
        assert resp.status_code == 200
        b_items = resp.json()["items"]
        b_actions = [a["action"] for a in b_items]
        assert "issue.created" in b_actions

        # User A's feed should NOT have the issue.created (B was the actor)
        resp = await client.get("/v1/activity", params={"actor": user_a["id"]})
        assert resp.status_code == 200
        a_items = resp.json()["items"]
        a_issue_events = [
            a for a in a_items if a["action"] == "issue.created"
        ]
        assert len(a_issue_events) == 0


# ---------------------------------------------------------------------------
# Full action vocabulary
# ---------------------------------------------------------------------------


class TestActivityActionVocabulary:
    """Scenario: All specified action types are correctly logged."""

    async def test_entry_created_action_logged(
        self,
        owner: AuthedFixture,
    ) -> None:
        """Creating an entry logs 'entry.created' activity."""
        client, user, token = owner
        resp = await client.post(
            "/v1/entries",
            json={"title": "Activity Test", "content_format": "markdown"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201

        resp = await client.get("/v1/activity", params={"actor": user["id"]})
        assert resp.status_code == 200
        items = resp.json()["items"]
        actions = {a["action"] for a in items}
        assert "entry.created" in actions

    async def test_all_issue_actions_logged(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Issue lifecycle generates 'issue.created', 'issue.commented',
        'issue.closed'."""
        client, user, token = owner
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="Issue Actions"
        )
        entry_id = entry["id"]

        # Create issue
        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Test issue", "body": "body"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        issue_num = resp.json()["number"]

        # Comment
        resp = await client.post(
            f"/v1/entries/{entry_id}/issues/{issue_num}/comments",
            json={"body": "A comment"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201

        # Close
        resp = await client.post(
            f"/v1/entries/{entry_id}/issues/{issue_num}/close",
            headers=auth_header(token),
        )
        assert resp.status_code == 200

        resp = await client.get("/v1/activity", params={"actor": user["id"]})
        assert resp.status_code == 200
        actions = {a["action"] for a in resp.json()["items"]}
        assert "issue.created" in actions
        assert "issue.commented" in actions
        assert "issue.closed" in actions

    async def test_all_edit_actions_logged(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Edit lifecycle generates 'edit.created' and 'edit.merged'."""
        client, user_a, token_a = owner
        _, user_b, token_b = other_user
        entry = await _create_ready_entry(
            client, token_a, e2e_session_factory, title="Edit Actions"
        )
        entry_id = entry["id"]

        # User B creates edit
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Improve data",
                "files": [{"path": "data.csv", "content": _b64("x,y")}],
            },
            headers=auth_header(token_b),
        )
        assert resp.status_code == 201
        edit_num = resp.json()["number"]

        # Owner merges
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{edit_num}/merge",
            headers=auth_header(token_a),
        )
        assert resp.status_code == 200

        # Check B has edit.created
        resp = await client.get("/v1/activity", params={"actor": user_b["id"]})
        assert resp.status_code == 200
        b_actions = {a["action"] for a in resp.json()["items"]}
        assert "edit.created" in b_actions

        # Check A has edit.merged
        resp = await client.get("/v1/activity", params={"actor": user_a["id"]})
        assert resp.status_code == 200
        a_actions = {a["action"] for a in resp.json()["items"]}
        assert "edit.merged" in a_actions
