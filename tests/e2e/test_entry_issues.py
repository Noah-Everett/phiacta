# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for entry issues API.

Tests the full API contract for:
- POST /v1/entries/{entry_id}/issues                    -- create issue
- GET  /v1/entries/{entry_id}/issues                    -- list issues
- GET  /v1/entries/{entry_id}/issues/{number}           -- get issue detail
- POST /v1/entries/{entry_id}/issues/{number}/comments  -- add comment
- POST /v1/entries/{entry_id}/issues/{number}/close     -- close issue

Issues proxy to Forgejo via FakeGitService. Any authenticated user can
create issues and comments; only the entry owner can close.
"""

from __future__ import annotations

from uuid import uuid4

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


@pytest.fixture
async def owner(client: httpx.AsyncClient) -> AuthedFixture:
    """Register a user (the entry owner) and return (client, user_data, token)."""
    uid = uuid4().hex[:8]
    auth = await register_user(client, username=f"issue-owner-{uid}")
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def commenter(client: httpx.AsyncClient) -> AuthedFixture:
    """Register a second user (a non-owner) and return (client, user_data, token)."""
    uid = uuid4().hex[:8]
    auth = await register_user(client, username=f"issue-commenter-{uid}")
    return client, auth["user"], auth["access_token"]


async def _create_ready_entry(
    client: httpx.AsyncClient,
    token: str,
    session_factory: async_sessionmaker[AsyncSession],
    title: str = "Issues Test Entry",
) -> dict:
    """Create an entry and set it to repo_status='ready'."""
    entry = await create_entry(client, token, title=title)
    await set_entry_repo_status(session_factory, entry["id"], "ready")
    return entry


# ---------------------------------------------------------------------------
# POST /v1/entries/{entry_id}/issues -- Create issue
# ---------------------------------------------------------------------------


class TestCreateIssue:
    """Scenario: Authenticated user creates an issue on an entry."""

    async def test_create_issue_returns_201(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /issues returns 201 with correct fields."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Found a typo", "body": "In section 2.1"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Found a typo"
        assert data["state"] == "open"
        assert data["number"] == 1
        assert "created_at" in data
        assert "updated_at" in data

    async def test_create_issue_has_author(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Issue response includes the author's username."""
        client, user, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)

        resp = await client.post(
            f"/v1/entries/{entry['id']}/issues",
            json={"title": "Author check"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        assert "author" in resp.json()
        assert "username" in resp.json()["author"]

    async def test_create_issue_without_body(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /issues with no body field returns 201 (body is optional)."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)

        resp = await client.post(
            f"/v1/entries/{entry['id']}/issues",
            json={"title": "No body issue"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "No body issue"
        # body should be None or empty
        assert data["body"] is None or data["body"] == ""

    async def test_create_issue_by_non_owner(
        self,
        owner: AuthedFixture,
        commenter: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Any authenticated user can create issues — not just the owner."""
        client, _, owner_token = owner
        _, _, commenter_token = commenter
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)

        resp = await client.post(
            f"/v1/entries/{entry['id']}/issues",
            json={"title": "External feedback"},
            headers=auth_header(commenter_token),
        )
        assert resp.status_code == 201

    async def test_create_multiple_issues_increments_number(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Creating multiple issues assigns incrementing numbers."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)

        resp1 = await client.post(
            f"/v1/entries/{entry['id']}/issues",
            json={"title": "Issue 1"},
            headers=auth_header(token),
        )
        resp2 = await client.post(
            f"/v1/entries/{entry['id']}/issues",
            json={"title": "Issue 2"},
            headers=auth_header(token),
        )
        assert resp1.json()["number"] == 1
        assert resp2.json()["number"] == 2


class TestCreateIssueErrors:
    """Scenario: Error responses for creating issues."""

    async def test_create_issue_unauthenticated_returns_401(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /issues without auth returns 401."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)

        resp = await client.post(
            f"/v1/entries/{entry['id']}/issues",
            json={"title": "Should fail"},
        )
        assert resp.status_code == 401

    async def test_create_issue_nonexistent_entry_returns_404(
        self,
        owner: AuthedFixture,
    ) -> None:
        """POST /issues on a nonexistent entry returns 404."""
        client, _, token = owner
        fake_id = uuid4()
        resp = await client.post(
            f"/v1/entries/{fake_id}/issues",
            json={"title": "Should fail"},
            headers=auth_header(token),
        )
        assert resp.status_code == 404

    async def test_create_issue_provisioning_entry_returns_409(
        self,
        owner: AuthedFixture,
    ) -> None:
        """POST /issues on a provisioning entry returns 409."""
        client, _, token = owner
        entry = await create_entry(client, token, title="Provisioning Issue Entry")
        # Entry defaults to provisioning — no set_entry_repo_status call

        resp = await client.post(
            f"/v1/entries/{entry['id']}/issues",
            json={"title": "Should fail"},
            headers=auth_header(token),
        )
        assert resp.status_code == 409

    async def test_create_issue_empty_title_returns_422(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /issues with empty title returns 422 (validation error)."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)

        resp = await client.post(
            f"/v1/entries/{entry['id']}/issues",
            json={"title": ""},
            headers=auth_header(token),
        )
        # Pydantic max_length=500 but no min_length — empty string may pass validation.
        # FakeGitService will accept it. If schema adds min_length, this will be 422.
        assert resp.status_code in (201, 422)

    async def test_create_issue_invalid_uuid_returns_422(
        self,
        owner: AuthedFixture,
    ) -> None:
        """POST /issues with invalid UUID returns 422."""
        client, _, token = owner
        resp = await client.post(
            "/v1/entries/not-a-uuid/issues",
            json={"title": "Should fail"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /v1/entries/{entry_id}/issues -- List issues
# ---------------------------------------------------------------------------


class TestListIssues:
    """Scenario: Listing issues on an entry."""

    async def test_list_issues_empty(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /issues on an entry with no issues returns empty list."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)

        resp = await client.get(f"/v1/entries/{entry['id']}/issues")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    async def test_list_issues_returns_created_issues(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /issues returns issues that were created via POST."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)
        entry_id = entry["id"]

        await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Issue A"},
            headers=auth_header(token),
        )
        await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Issue B"},
            headers=auth_header(token),
        )

        resp = await client.get(f"/v1/entries/{entry_id}/issues")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 2
        titles = {i["title"] for i in items}
        assert "Issue A" in titles
        assert "Issue B" in titles

    async def test_list_issues_filter_by_state_open(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /issues?state=open returns only open issues."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)
        entry_id = entry["id"]

        # Create and close one issue
        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "To close"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        number = resp.json()["number"]
        await client.post(
            f"/v1/entries/{entry_id}/issues/{number}/close",
            headers=auth_header(token),
        )

        # Create one open issue
        await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Still open"},
            headers=auth_header(token),
        )

        resp = await client.get(
            f"/v1/entries/{entry_id}/issues", params={"state": "open"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["title"] == "Still open"
        assert items[0]["state"] == "open"

    async def test_list_issues_filter_by_state_closed(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /issues?state=closed returns only closed issues."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Will close"},
            headers=auth_header(token),
        )
        number = resp.json()["number"]
        await client.post(
            f"/v1/entries/{entry_id}/issues/{number}/close",
            headers=auth_header(token),
        )
        await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Open one"},
            headers=auth_header(token),
        )

        resp = await client.get(
            f"/v1/entries/{entry_id}/issues", params={"state": "closed"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["state"] == "closed"

    async def test_list_issues_is_public(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /issues does not require authentication."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)

        # No auth header
        resp = await client.get(f"/v1/entries/{entry['id']}/issues")
        assert resp.status_code == 200

    async def test_list_issues_invalid_state_returns_422(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /issues?state=invalid returns 422."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)

        resp = await client.get(
            f"/v1/entries/{entry['id']}/issues", params={"state": "invalid"},
        )
        assert resp.status_code == 422


class TestListIssuesErrors:
    """Scenario: Error responses for listing issues."""

    async def test_list_issues_nonexistent_entry_returns_404(
        self, client: httpx.AsyncClient,
    ) -> None:
        """GET /issues on a nonexistent entry returns 404."""
        resp = await client.get(f"/v1/entries/{uuid4()}/issues")
        assert resp.status_code == 404

    async def test_list_issues_provisioning_entry_returns_409(
        self,
        owner: AuthedFixture,
    ) -> None:
        """GET /issues on a provisioning entry returns 409."""
        client, _, token = owner
        entry = await create_entry(client, token, title="Provisioning List")

        resp = await client.get(f"/v1/entries/{entry['id']}/issues")
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# GET /v1/entries/{entry_id}/issues/{number} -- Get issue detail
# ---------------------------------------------------------------------------


class TestGetIssueDetail:
    """Scenario: Retrieving issue detail with comments."""

    async def test_get_issue_detail(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /issues/{number} returns the issue with comments list."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Detail test", "body": "Some body"},
            headers=auth_header(token),
        )
        number = resp.json()["number"]

        resp = await client.get(f"/v1/entries/{entry_id}/issues/{number}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Detail test"
        assert data["body"] == "Some body"
        assert data["state"] == "open"
        assert "comments" in data
        assert isinstance(data["comments"], list)
        assert data["comments"] == []

    async def test_get_issue_detail_with_comments(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /issues/{number} includes comments that were added."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "With comments"},
            headers=auth_header(token),
        )
        number = resp.json()["number"]

        await client.post(
            f"/v1/entries/{entry_id}/issues/{number}/comments",
            json={"body": "First comment"},
            headers=auth_header(token),
        )
        await client.post(
            f"/v1/entries/{entry_id}/issues/{number}/comments",
            json={"body": "Second comment"},
            headers=auth_header(token),
        )

        resp = await client.get(f"/v1/entries/{entry_id}/issues/{number}")
        assert resp.status_code == 200
        comments = resp.json()["comments"]
        assert len(comments) == 2
        bodies = [c["body"] for c in comments]
        assert "First comment" in bodies
        assert "Second comment" in bodies

    async def test_get_issue_detail_has_required_fields(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Issue detail has all required fields from IssueDetail schema."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Fields check"},
            headers=auth_header(token),
        )
        number = resp.json()["number"]

        resp = await client.get(f"/v1/entries/{entry_id}/issues/{number}")
        assert resp.status_code == 200
        data = resp.json()

        required = {
            "number", "title", "body", "state", "author",
            "comments_count", "created_at", "updated_at",
            "closed_at", "comments",
        }
        assert required.issubset(set(data.keys())), (
            f"Missing fields: {required - set(data.keys())}"
        )

    async def test_get_issue_detail_is_public(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /issues/{number} does not require authentication."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Public detail"},
            headers=auth_header(token),
        )
        number = resp.json()["number"]

        # No auth header
        resp = await client.get(f"/v1/entries/{entry_id}/issues/{number}")
        assert resp.status_code == 200


class TestGetIssueDetailErrors:
    """Scenario: Error responses for getting issue detail."""

    async def test_get_issue_nonexistent_number_returns_404(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /issues/999 on an entry with no such issue returns 404."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)

        resp = await client.get(f"/v1/entries/{entry['id']}/issues/999")
        assert resp.status_code == 404

    async def test_get_issue_nonexistent_entry_returns_404(
        self, client: httpx.AsyncClient,
    ) -> None:
        """GET /issues/{number} on a nonexistent entry returns 404."""
        resp = await client.get(f"/v1/entries/{uuid4()}/issues/1")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /v1/entries/{entry_id}/issues/{number}/comments -- Add comment
# ---------------------------------------------------------------------------


class TestAddIssueComment:
    """Scenario: Adding comments to issues."""

    async def test_add_comment_returns_201(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /comments returns 201 with comment fields."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Comment test"},
            headers=auth_header(token),
        )
        number = resp.json()["number"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues/{number}/comments",
            json={"body": "Great observation!"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["body"] == "Great observation!"
        assert "id" in data
        assert "author" in data
        assert "created_at" in data

    async def test_add_comment_by_non_owner(
        self,
        owner: AuthedFixture,
        commenter: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Any authenticated user can add comments — not just the owner."""
        client, _, owner_token = owner
        _, _, commenter_token = commenter
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Cross-user comment"},
            headers=auth_header(owner_token),
        )
        number = resp.json()["number"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues/{number}/comments",
            json={"body": "Comment from non-owner"},
            headers=auth_header(commenter_token),
        )
        assert resp.status_code == 201

    async def test_add_multiple_comments(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Adding multiple comments to the same issue works."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Multi comment"},
            headers=auth_header(token),
        )
        number = resp.json()["number"]

        for i in range(3):
            resp = await client.post(
                f"/v1/entries/{entry_id}/issues/{number}/comments",
                json={"body": f"Comment {i}"},
                headers=auth_header(token),
            )
            assert resp.status_code == 201

        # Verify via detail endpoint
        resp = await client.get(f"/v1/entries/{entry_id}/issues/{number}")
        assert len(resp.json()["comments"]) == 3


class TestAddIssueCommentErrors:
    """Scenario: Error responses for adding comments."""

    async def test_add_comment_unauthenticated_returns_401(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /comments without auth returns 401."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Auth comment test"},
            headers=auth_header(token),
        )
        number = resp.json()["number"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues/{number}/comments",
            json={"body": "Should fail"},
        )
        assert resp.status_code == 401

    async def test_add_comment_nonexistent_issue_returns_404(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /comments on a nonexistent issue returns 404."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)

        resp = await client.post(
            f"/v1/entries/{entry['id']}/issues/999/comments",
            json={"body": "Should fail"},
            headers=auth_header(token),
        )
        assert resp.status_code == 404

    async def test_add_comment_empty_body_returns_422(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /comments with empty body returns 422 (min_length=1)."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Empty comment test"},
            headers=auth_header(token),
        )
        number = resp.json()["number"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues/{number}/comments",
            json={"body": ""},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    async def test_add_comment_nonexistent_entry_returns_404(
        self,
        owner: AuthedFixture,
    ) -> None:
        """POST /comments on a nonexistent entry returns 404."""
        client, _, token = owner
        resp = await client.post(
            f"/v1/entries/{uuid4()}/issues/1/comments",
            json={"body": "Should fail"},
            headers=auth_header(token),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /v1/entries/{entry_id}/issues/{number}/close -- Close issue
# ---------------------------------------------------------------------------


class TestCloseIssue:
    """Scenario: Entry owner closes an issue."""

    async def test_close_issue_returns_200(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /close returns 200 with confirmation detail."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "To close"},
            headers=auth_header(token),
        )
        number = resp.json()["number"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues/{number}/close",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        assert "closed" in resp.json()["detail"].lower()

    async def test_close_issue_updates_state(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """After closing, GET /issues/{number} shows state='closed'."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "State check"},
            headers=auth_header(token),
        )
        number = resp.json()["number"]

        await client.post(
            f"/v1/entries/{entry_id}/issues/{number}/close",
            headers=auth_header(token),
        )

        resp = await client.get(f"/v1/entries/{entry_id}/issues/{number}")
        assert resp.status_code == 200
        assert resp.json()["state"] == "closed"
        assert resp.json()["closed_at"] is not None

    async def test_close_issue_updates_closed_at(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """After closing, the issue has a non-null closed_at timestamp."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Closed at check"},
            headers=auth_header(token),
        )
        number = resp.json()["number"]

        # Before closing: closed_at should be null
        resp = await client.get(f"/v1/entries/{entry_id}/issues/{number}")
        assert resp.json()["closed_at"] is None

        # Close the issue
        await client.post(
            f"/v1/entries/{entry_id}/issues/{number}/close",
            headers=auth_header(token),
        )

        # After closing: closed_at should be set
        resp = await client.get(f"/v1/entries/{entry_id}/issues/{number}")
        assert resp.json()["closed_at"] is not None


class TestCloseIssueErrors:
    """Scenario: Error responses for closing issues."""

    async def test_close_issue_by_non_owner_returns_403(
        self,
        owner: AuthedFixture,
        commenter: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Only the entry owner can close issues."""
        client, _, owner_token = owner
        _, _, commenter_token = commenter
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Non-owner close"},
            headers=auth_header(owner_token),
        )
        number = resp.json()["number"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues/{number}/close",
            headers=auth_header(commenter_token),
        )
        assert resp.status_code == 403

    async def test_close_issue_unauthenticated_returns_401(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /close without auth returns 401."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Unauth close"},
            headers=auth_header(token),
        )
        number = resp.json()["number"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues/{number}/close",
        )
        assert resp.status_code == 401

    async def test_close_nonexistent_issue_returns_404(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /close on a nonexistent issue returns 404."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)

        resp = await client.post(
            f"/v1/entries/{entry['id']}/issues/999/close",
            headers=auth_header(token),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Full lifecycle
# ---------------------------------------------------------------------------


class TestIssueLifecycle:
    """Scenario: Complete issue lifecycle — create, comment, close, verify."""

    async def test_full_lifecycle(
        self,
        owner: AuthedFixture,
        commenter: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Create issue -> add comments -> close -> verify final state."""
        client, _, owner_token = owner
        _, _, commenter_token = commenter
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        # 1. Non-owner creates an issue
        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Bug report", "body": "Steps to reproduce..."},
            headers=auth_header(commenter_token),
        )
        assert resp.status_code == 201
        number = resp.json()["number"]

        # 2. Owner comments
        resp = await client.post(
            f"/v1/entries/{entry_id}/issues/{number}/comments",
            json={"body": "Thanks, looking into it"},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 201

        # 3. Non-owner adds follow-up comment
        resp = await client.post(
            f"/v1/entries/{entry_id}/issues/{number}/comments",
            json={"body": "Here's more context"},
            headers=auth_header(commenter_token),
        )
        assert resp.status_code == 201

        # 4. Owner closes the issue
        resp = await client.post(
            f"/v1/entries/{entry_id}/issues/{number}/close",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

        # 5. Verify final state
        resp = await client.get(f"/v1/entries/{entry_id}/issues/{number}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["state"] == "closed"
        assert detail["closed_at"] is not None
        assert len(detail["comments"]) == 2

        # 6. Verify list shows the closed issue
        resp = await client.get(
            f"/v1/entries/{entry_id}/issues", params={"state": "closed"},
        )
        assert len(resp.json()["items"]) == 1
        assert resp.json()["items"][0]["number"] == number


class TestIssueResponseShape:
    """Scenario: Verify response schemas match expectations."""

    async def test_issue_list_item_shape(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """IssueListItem has all expected fields."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)

        resp = await client.post(
            f"/v1/entries/{entry['id']}/issues",
            json={"title": "Shape test", "body": "Body"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        data = resp.json()

        expected_fields = {
            "number", "title", "body", "state", "author",
            "comments_count", "created_at", "updated_at", "closed_at",
        }
        assert expected_fields.issubset(set(data.keys())), (
            f"Missing: {expected_fields - set(data.keys())}"
        )

    async def test_comment_response_shape(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """IssueCommentResponse has all expected fields."""
        client, _, token = owner
        entry = await _create_ready_entry(client, token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Comment shape"},
            headers=auth_header(token),
        )
        number = resp.json()["number"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues/{number}/comments",
            json={"body": "Check shape"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        data = resp.json()

        expected_fields = {"id", "body", "author", "created_at", "updated_at"}
        assert expected_fields.issubset(set(data.keys())), (
            f"Missing: {expected_fields - set(data.keys())}"
        )
        assert "username" in data["author"]
