# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for the Entity Registry feature.

Tests that entity rows are created alongside domain objects (users, entries,
issues, edits, comments) via their respective API endpoints. Since entities
are a behind-the-scenes persistence concern, we verify their existence
indirectly through the activity feed (GET /v1/activity?actor={id}) and by
confirming that existing features continue to work correctly.

Entity creation is a side-effect of existing endpoints:
- POST /v1/auth/register       -- creates Entity(type='user')
- POST /v1/entries              -- creates Entity(type='entry')
- POST /v1/entries/{id}/issues  -- creates Entity(type='issue')
- POST /v1/entries/{id}/edits   -- creates Entity(type='edit')
- POST /v1/entries/{id}/issues/{n}/comments -- creates Entity(type='comment')
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
    """Encode text as base64 string for file content."""
    return base64.b64encode(text.encode()).decode()


@pytest.fixture
async def owner(client: httpx.AsyncClient) -> AuthedFixture:
    """Register a user (the entry owner) and return (client, user_data, token)."""
    uid = uuid4().hex[:8]
    auth = await register_user(client, handle=f"entity-owner-{uid}")
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def other_user(client: httpx.AsyncClient) -> AuthedFixture:
    """Register a second user and return (client, user_data, token)."""
    uid = uuid4().hex[:8]
    auth = await register_user(client, handle=f"entity-other-{uid}")
    return client, auth["user"], auth["access_token"]


async def _create_ready_entry(
    client: httpx.AsyncClient,
    token: str,
    session_factory: async_sessionmaker[AsyncSession],
    title: str = "Entity Test Entry",
) -> dict:
    """Create an entry and set it to repo_status='ready'."""
    entry = await create_entry(client, token, title=title)
    await set_entry_repo_status(session_factory, entry["id"], "ready")
    return entry


# ---------------------------------------------------------------------------
# Entity creation via entry lifecycle
# ---------------------------------------------------------------------------


class TestEntryCreatesEntity:
    """Scenario: Creating an entry also creates an Entity row, observable
    via the activity feed which logs 'entry.created'."""

    async def test_entry_creation_appears_in_activity_feed(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /v1/entries creates an Entity(type='entry') and logs
        activity 'entry.created', visible in the user's activity feed."""
        client, user, token = owner
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="Gravitation"
        )
        entry_id = entry["id"]
        user_id = user["id"]

        resp = await client.get("/v1/activity", params={"actor": user_id})
        assert resp.status_code == 200
        data = resp.json()
        items = data["items"]

        # Must contain exactly one 'entry.created' event for this entry
        entry_created = [
            a for a in items
            if a["action"] == "entry.created" and a["entity_id"] == entry_id
        ]
        assert len(entry_created) == 1
        event = entry_created[0]
        assert event["entity_type"] == "entry"
        assert event["entity_id"] == entry_id
        assert event["created_at"] is not None

    async def test_multiple_entries_each_have_activity(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Creating N entries results in N 'entry.created' activity events."""
        client, user, token = owner
        entry_ids = []
        for i in range(3):
            entry = await _create_ready_entry(
                client, token, e2e_session_factory, title=f"Entry {i}"
            )
            entry_ids.append(entry["id"])

        resp = await client.get("/v1/activity", params={"actor": user["id"]})
        assert resp.status_code == 200
        items = resp.json()["items"]

        created_events = [a for a in items if a["action"] == "entry.created"]
        created_entity_ids = {a["entity_id"] for a in created_events}
        for eid in entry_ids:
            assert eid in created_entity_ids, (
                f"Entry {eid} missing from activity feed"
            )

    async def test_entry_id_is_also_entity_id(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """The entry UUID serves as both the entry PK and entity PK
        (shared-PK strategy). The activity event's entity_id must match
        the entry's id exactly."""
        client, user, token = owner
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="Shared PK Test"
        )

        resp = await client.get("/v1/activity", params={"actor": user["id"]})
        assert resp.status_code == 200
        items = resp.json()["items"]
        created = [
            a for a in items
            if a["action"] == "entry.created"
            and a["entity_id"] == entry["id"]
        ]
        assert len(created) == 1
        # Entry should still be fetchable by its id (which is the entity id)
        entry_resp = await client.get(f"/v1/entries/{entry['id']}")
        assert entry_resp.status_code == 200
        assert entry_resp.json()["id"] == entry["id"]


# ---------------------------------------------------------------------------
# Entity creation via user registration
# ---------------------------------------------------------------------------


class TestUserRegistrationCreatesEntity:
    """Scenario: Registering a user creates an Entity(type='user').
    Per spec, NO activity is logged for user registration."""

    async def test_user_registration_does_not_log_activity(
        self, client: httpx.AsyncClient,
    ) -> None:
        """New user has an empty activity feed -- no activity logged for
        registration itself."""
        auth = await register_user(client, handle="fresh-user")
        user_id = auth["user"]["id"]

        resp = await client.get("/v1/activity", params={"actor": user_id})
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["next_cursor"] is None

    async def test_user_entity_id_matches_user_id(
        self, client: httpx.AsyncClient,
    ) -> None:
        """The user UUID is the entity UUID (shared-PK). User profile
        endpoint must still return the correct user after entity
        registration."""
        auth = await register_user(client, handle="entity-user-pk")
        user_id = auth["user"]["id"]

        # The user should be fetchable via the user endpoint
        resp = await client.get(f"/v1/users/{user_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == user_id
        assert resp.json()["handle"] == "entity-user-pk"

    async def test_first_user_entity_has_no_created_by(
        self, client: httpx.AsyncClient,
    ) -> None:
        """The first user's entity has created_by=NULL (self-creating).
        We verify this indirectly: user registration succeeds even when
        there are no existing users (no chicken-and-egg problem)."""
        # This test implicitly verifies that created_by=NULL works for
        # the first user -- if the Entity FK required a valid created_by,
        # this would fail.
        auth = await register_user(client, handle="first-ever-user")
        assert auth["user"]["id"] is not None
        assert auth["access_token"] is not None


# ---------------------------------------------------------------------------
# Entity creation via issue lifecycle
# ---------------------------------------------------------------------------


class TestIssueCreatesEntity:
    """Scenario: Creating an issue creates an Entity(type='issue') with
    parent_id pointing to the entry's entity, and external_ref set to
    'issues/{number}'."""

    async def test_issue_creation_generates_activity(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /entries/{id}/issues creates Entity + logs 'issue.created'."""
        client, owner_data, owner_token = owner
        _, other_data, other_token = other_user
        entry = await _create_ready_entry(
            client, owner_token, e2e_session_factory, title="Issue Target"
        )
        entry_id = entry["id"]

        # Create an issue as other_user
        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Found a bug", "body": "Description here"},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 201

        # Check other_user's activity feed
        resp = await client.get("/v1/activity", params={"actor": other_data["id"]})
        assert resp.status_code == 200
        items = resp.json()["items"]
        issue_events = [a for a in items if a["action"] == "issue.created"]
        assert len(issue_events) >= 1

        event = issue_events[0]
        assert event["entity_type"] == "issue"
        assert event["parent_id"] == entry_id

    async def test_issue_entity_has_correct_parent_and_metadata(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """The issue entity's parent_id matches the entry_id, and
        the activity metadata includes the issue title."""
        client, user, token = owner
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="Parent Entry"
        )
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Methodology concern", "body": "Details..."},
            headers=auth_header(token),
        )
        assert resp.status_code == 201

        resp = await client.get("/v1/activity", params={"actor": user["id"]})
        assert resp.status_code == 200
        items = resp.json()["items"]
        issue_events = [a for a in items if a["action"] == "issue.created"]
        assert len(issue_events) >= 1
        event = issue_events[0]
        assert event["parent_id"] == entry_id
        # Metadata should contain the title
        assert event["metadata"] is not None
        assert "title" in event["metadata"]
        assert event["metadata"]["title"] == "Methodology concern"

    async def test_issue_comment_creates_entity_and_activity(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /entries/{id}/issues/{n}/comments creates Entity(type='comment')
        with parent_id=issue_entity_id and logs 'issue.commented'."""
        client, owner_data, owner_token = owner
        _, other_data, other_token = other_user
        entry = await _create_ready_entry(
            client, owner_token, e2e_session_factory, title="Commented Entry"
        )
        entry_id = entry["id"]

        # Create issue
        issue_resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Needs review", "body": "Please check"},
            headers=auth_header(other_token),
        )
        assert issue_resp.status_code == 201
        issue_number = issue_resp.json()["number"]

        # Add comment as owner
        comment_resp = await client.post(
            f"/v1/entries/{entry_id}/issues/{issue_number}/comments",
            json={"body": "I'll take a look at this."},
            headers=auth_header(owner_token),
        )
        assert comment_resp.status_code == 201

        # Check owner's activity feed for 'issue.commented'
        resp = await client.get("/v1/activity", params={"actor": owner_data["id"]})
        assert resp.status_code == 200
        items = resp.json()["items"]
        comment_events = [a for a in items if a["action"] == "issue.commented"]
        assert len(comment_events) >= 1

    async def test_issue_close_logs_activity(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /entries/{id}/issues/{n}/close logs 'issue.closed' activity
        (no new entity created)."""
        client, user, token = owner
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="Close Me"
        )
        entry_id = entry["id"]

        # Create then close issue
        issue_resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "To be closed", "body": "Closing soon"},
            headers=auth_header(token),
        )
        assert issue_resp.status_code == 201
        issue_number = issue_resp.json()["number"]

        close_resp = await client.post(
            f"/v1/entries/{entry_id}/issues/{issue_number}/close",
            headers=auth_header(token),
        )
        assert close_resp.status_code == 200

        resp = await client.get("/v1/activity", params={"actor": user["id"]})
        assert resp.status_code == 200
        items = resp.json()["items"]
        close_events = [a for a in items if a["action"] == "issue.closed"]
        assert len(close_events) >= 1

    async def test_issue_lifecycle_creates_ordered_events(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Full issue lifecycle: create -> comment -> close generates 3
        activity events in reverse chronological order."""
        client, user, token = owner
        entry = await _create_ready_entry(
            client, token, e2e_session_factory, title="Lifecycle Entry"
        )
        entry_id = entry["id"]

        # Create issue
        resp = await client.post(
            f"/v1/entries/{entry_id}/issues",
            json={"title": "Lifecycle issue", "body": "Testing lifecycle"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        issue_number = resp.json()["number"]

        # Comment
        resp = await client.post(
            f"/v1/entries/{entry_id}/issues/{issue_number}/comments",
            json={"body": "Working on it"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201

        # Close
        resp = await client.post(
            f"/v1/entries/{entry_id}/issues/{issue_number}/close",
            headers=auth_header(token),
        )
        assert resp.status_code == 200

        # Check activity feed -- should have all 3 events in reverse
        # chronological order
        resp = await client.get("/v1/activity", params={"actor": user["id"]})
        assert resp.status_code == 200
        items = resp.json()["items"]
        issue_actions = [
            a["action"] for a in items
            if a["action"] in (
                "issue.created", "issue.commented", "issue.closed",
            )
        ]
        # In reverse chronological order: closed is most recent
        assert "issue.closed" in issue_actions
        assert "issue.commented" in issue_actions
        assert "issue.created" in issue_actions
        # Verify ordering: closed before commented before created
        closed_idx = issue_actions.index("issue.closed")
        commented_idx = issue_actions.index("issue.commented")
        created_idx = issue_actions.index("issue.created")
        assert closed_idx < commented_idx < created_idx


# ---------------------------------------------------------------------------
# Entity creation via edit lifecycle
# ---------------------------------------------------------------------------


class TestEditCreatesEntity:
    """Scenario: Creating/merging/closing an edit proposal creates entities
    and logs activity."""

    async def test_edit_creation_generates_activity(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /entries/{id}/edits creates Entity(type='edit') and logs
        'edit.created' with correct parent_id."""
        client, _, owner_token = owner
        _, other_data, other_token = other_user
        entry = await _create_ready_entry(
            client, owner_token, e2e_session_factory, title="Edit Target"
        )
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Fix methodology section",
                "files": [{"path": "README.md", "content": _b64("# Fixed")}],
            },
            headers=auth_header(other_token),
        )
        assert resp.status_code == 201

        resp = await client.get("/v1/activity", params={"actor": other_data["id"]})
        assert resp.status_code == 200
        items = resp.json()["items"]
        edit_events = [a for a in items if a["action"] == "edit.created"]
        assert len(edit_events) >= 1
        event = edit_events[0]
        assert event["entity_type"] == "edit"
        assert event["parent_id"] == entry_id

    async def test_edit_merge_logs_activity(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Merging an edit proposal logs 'edit.merged' in the actor's
        activity feed."""
        client, owner_data, owner_token = owner
        _, _, other_token = other_user
        entry = await _create_ready_entry(
            client, owner_token, e2e_session_factory, title="Merge Target"
        )
        entry_id = entry["id"]

        # Create edit as other user
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Improve references",
                "files": [
                    {"path": "refs.bib", "content": _b64("@article{}")},
                ],
            },
            headers=auth_header(other_token),
        )
        assert resp.status_code == 201
        edit_number = resp.json()["number"]

        # Merge as owner
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{edit_number}/merge",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

        resp = await client.get("/v1/activity", params={"actor": owner_data["id"]})
        assert resp.status_code == 200
        items = resp.json()["items"]
        merge_events = [a for a in items if a["action"] == "edit.merged"]
        assert len(merge_events) >= 1

    async def test_edit_close_logs_activity(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Closing an edit proposal logs 'edit.closed' in the actor's
        activity feed."""
        client, owner_data, owner_token = owner
        _, _, other_token = other_user
        entry = await _create_ready_entry(
            client, owner_token, e2e_session_factory, title="Close Edit Target"
        )
        entry_id = entry["id"]

        # Create edit
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Bad proposal",
                "files": [{"path": "bad.txt", "content": _b64("nope")}],
            },
            headers=auth_header(other_token),
        )
        assert resp.status_code == 201
        edit_number = resp.json()["number"]

        # Close as owner
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{edit_number}/close",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

        resp = await client.get("/v1/activity", params={"actor": owner_data["id"]})
        assert resp.status_code == 200
        items = resp.json()["items"]
        close_events = [a for a in items if a["action"] == "edit.closed"]
        assert len(close_events) >= 1

    async def test_edit_lifecycle_creates_ordered_events(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Full edit lifecycle: create -> merge generates 2 activity events
        attributed to the correct actors."""
        client, owner_data, owner_token = owner
        _, other_data, other_token = other_user
        entry = await _create_ready_entry(
            client, owner_token, e2e_session_factory, title="Edit Lifecycle"
        )
        entry_id = entry["id"]

        # Create edit as other
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Lifecycle edit",
                "files": [{"path": "data.csv", "content": _b64("a,b")}],
            },
            headers=auth_header(other_token),
        )
        assert resp.status_code == 201
        edit_number = resp.json()["number"]

        # Merge as owner
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{edit_number}/merge",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

        # Other user should see 'edit.created'
        resp = await client.get("/v1/activity", params={"actor": other_data["id"]})
        assert resp.status_code == 200
        other_items = resp.json()["items"]
        other_actions = [a["action"] for a in other_items]
        assert "edit.created" in other_actions

        # Owner should see 'edit.merged'
        resp = await client.get("/v1/activity", params={"actor": owner_data["id"]})
        assert resp.status_code == 200
        owner_items = resp.json()["items"]
        owner_actions = [a["action"] for a in owner_items]
        assert "edit.merged" in owner_actions


# ---------------------------------------------------------------------------
# Entity creation via archive/unarchive
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Regression: existing features still work
# ---------------------------------------------------------------------------


class TestRegressionEntryOperations:
    """Scenario: Existing entry operations must continue to work after
    entity registration is added."""

    async def test_entry_creation_still_returns_correct_shape(
        self,
        owner: AuthedFixture,
    ) -> None:
        """POST /v1/entries still returns the expected entry response fields."""
        client, user, token = owner
        resp = await client.post(
            "/v1/entries",
            json={"title": "Regression Test", "content_format": "markdown"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Regression Test"
        assert data["visibility"] == "public"
        assert data["repo_status"] == "provisioning"
        assert data["created_by"] == user["id"]

    async def test_entry_get_still_works_after_entity_creation(
        self,
        owner: AuthedFixture,
    ) -> None:
        """GET /v1/entries/{id} works after entity registration is wired in."""
        client, _, token = owner
        resp = await client.post(
            "/v1/entries",
            json={"title": "Fetchable"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        entry_id = resp.json()["id"]

        resp = await client.get(f"/v1/entries/{entry_id}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Fetchable"

    async def test_user_registration_still_returns_correct_shape(
        self, client: httpx.AsyncClient,
    ) -> None:
        """POST /v1/auth/register still returns user + access_token."""
        uid = uuid4().hex[:8]
        resp = await client.post("/v1/auth/register", json={
            "handle": f"regression-{uid}",
            "password": "TestPassword123!",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "user" in data
        assert "access_token" in data
        assert data["user"]["handle"] == f"regression-{uid}"
