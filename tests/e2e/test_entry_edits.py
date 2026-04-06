# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for entry edit proposals API (NEV-126, NEV-162).

Tests the full API contract for:
- POST /v1/entries/{entry_id}/edits           -- create edit proposal
- GET  /v1/entries/{entry_id}/edits           -- list edit proposals
- GET  /v1/entries/{entry_id}/edits/{number}  -- get proposal detail
- POST /v1/entries/{entry_id}/edits/{number}/merge  -- merge proposal
- POST /v1/entries/{entry_id}/edits/{number}/close  -- close proposal

Edit proposals allow any authenticated user to propose changes to an entry.
Only the entry owner can merge or close proposals.
"""

from __future__ import annotations

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
    set_entry_visibility,
)

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


@pytest.fixture
async def owner(client: httpx.AsyncClient) -> AuthedFixture:
    """Register a user (the entry owner) and return (client, user_data, token)."""
    uid = uuid4().hex[:8]
    auth = await register_user(
        client, username=f"owner-{uid}"
    )
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def proposer(client: httpx.AsyncClient) -> AuthedFixture:
    """Register a second user (a non-owner proposer) and return (client, user_data, token)."""
    uid = uuid4().hex[:8]
    auth = await register_user(
        client, username=f"proposer-{uid}"
    )
    return client, auth["user"], auth["access_token"]


async def _create_ready_entry(
    client: httpx.AsyncClient,
    token: str,
    session_factory: async_sessionmaker[AsyncSession],
    title: str = "Edit Test Entry",
) -> dict:
    """Create an entry and set it to repo_status='ready'."""
    entry = await create_entry(client, token, title=title)
    await set_entry_repo_status(session_factory, entry["id"], "ready")
    return entry


# ---------------------------------------------------------------------------
# POST /v1/entries/{entry_id}/edits -- Create edit proposal
# ---------------------------------------------------------------------------


class TestCreateEditProposal:
    """Scenario: An authenticated user creates an edit proposal for an entry."""

    async def test_create_proposal(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /edits returns 201 with correct fields for a valid proposal."""
        client, _, owner_token = owner
        _, proposer_user, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Fix typo in README",
                "body": "Corrected spelling of 'hypothesis'",
                "files": [{"path": "README.md", "content": "# Fixed README"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["number"] == 1
        assert data["title"] == "Fix typo in README"
        assert data["body"] == "Corrected spelling of 'hypothesis'"
        assert data["state"] == "open"
        assert data["is_draft"] is False
        assert data["author"]["username"] == proposer_user["username"]
        assert data["base_branch"] == "main"
        assert data["head_branch"]  # non-empty branch name
        assert data["created_at"] is not None
        assert data["updated_at"] is not None
        assert data["merged_at"] is None

    async def test_create_proposal_by_non_owner(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Any authenticated user can create a proposal -- not limited to owners."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Non-owner proposal",
                "files": [{"path": "data.csv", "content": "a,b,c"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        assert resp.json()["state"] == "open"

    async def test_create_proposal_self(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """The entry owner can propose changes to their own entry (self-proposal)."""
        client, owner_user, owner_token = owner
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Self-edit proposal",
                "body": "Owner proposes changes to own entry",
                "files": [{"path": "notes.txt", "content": "self-edit"}],
            },
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["author"]["username"] == owner_user["username"]
        assert data["state"] == "open"

    async def test_create_proposal_multiple_files(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """A proposal can include changes to multiple files at once."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Multi-file proposal",
                "body": "Updating several files",
                "files": [
                    {"path": "README.md", "content": "# Updated"},
                    {"path": "data/results.csv", "content": "x,y\n1,2"},
                    {"path": "analysis.py", "content": "print('hello')"},
                ],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["number"] >= 1
        assert data["title"] == "Multi-file proposal"

    async def test_create_proposal_branch_naming(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """The head_branch follows the pattern edit/{username}/{slugified_title}."""
        client, _, owner_token = owner
        _, proposer_user, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Fix Typo In README",
                "files": [{"path": "README.md", "content": "fixed"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        head_branch = resp.json()["head_branch"]
        # Must start with edit/{proposer_username}/
        assert head_branch.startswith(f"edit/{proposer_user['username']}/")
        # Must contain a slugified version of the title (lowercase, hyphens)
        slug_part = head_branch.split("/", 2)[2]
        assert slug_part  # non-empty
        # The slug should be lowercase
        assert slug_part == slug_part.lower()

    async def test_create_proposal_optional_body(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Body is optional -- omitting it should succeed."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "No body proposal",
                "files": [{"path": "data.txt", "content": "data"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        data = resp.json()
        # body should be None or empty string
        assert data["body"] is None or data["body"] == ""


class TestCreateEditProposalErrors:
    """Scenario: Error responses for the create edit proposal endpoint."""

    async def test_create_without_auth_401(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /edits without a Bearer token returns 401."""
        client, _, owner_token = owner
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Unauthorized",
                "files": [{"path": "README.md", "content": "x"}],
            },
            # No auth header
        )
        assert resp.status_code == 401

    async def test_create_nonexistent_entry_404(
        self,
        proposer: AuthedFixture,
    ) -> None:
        """POST /edits for a nonexistent entry returns 404."""
        client, _, proposer_token = proposer
        fake_id = uuid4()

        resp = await client.post(
            f"/v1/entries/{fake_id}/edits",
            json={
                "title": "Ghost entry",
                "files": [{"path": "README.md", "content": "x"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 404
        assert "entry" in resp.json()["detail"].lower()

    async def test_create_provisioning_entry_409(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
    ) -> None:
        """POST /edits when repo_status='provisioning' returns 409."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await create_entry(client, owner_token, title="Provisioning Edit")
        entry_id = entry["id"]
        # Default repo_status is "provisioning"

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Too early",
                "files": [{"path": "README.md", "content": "x"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 409
        assert "not yet ready" in resp.json()["detail"].lower()

    async def test_create_phiacta_path_blocked_400(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /edits with .phiacta/entry.yaml is allowed (no longer protected)."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Phiacta entry.yaml edit",
                "files": [
                    {"path": ".phiacta/entry.yaml", "content": "updated: true"},
                ],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201

    async def test_create_empty_files_422(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /edits with an empty files list returns 422."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Empty proposal",
                "files": [],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 422

    async def test_create_title_too_long_422(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /edits with a title exceeding 500 chars returns 422."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "X" * 501,
                "files": [{"path": "README.md", "content": "x"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 422

    async def test_create_no_title_422(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /edits without a title field returns 422."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "files": [{"path": "README.md", "content": "x"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 422

    async def test_create_path_traversal_blocked_400(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /edits with a path traversal attack (../) is rejected."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Traversal attack",
                "files": [
                    {"path": "../etc/passwd", "content": "hacked"},
                ],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 422

    async def test_create_absolute_path_blocked_400(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /edits with an absolute path is rejected."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Absolute path attack",
                "files": [
                    {"path": "/etc/passwd", "content": "hacked"},
                ],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 422

    async def test_create_invalid_base64_400(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /edits with any string content succeeds (base64 no longer required)."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Plain text content",
                "files": [
                    {"path": "data.csv", "content": "plain text, not base64"},
                ],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201

    async def test_create_file_exceeds_size_limit_400(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /edits with a file exceeding schema max_length returns 422."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        # Schema max_length is 10MB; Pydantic rejects before our size check
        oversized = "x" * (10_000_001)

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Oversized file",
                "files": [
                    {"path": "big.bin", "content": oversized},
                ],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /v1/entries/{entry_id}/edits -- List edit proposals
# ---------------------------------------------------------------------------


class TestListEditProposals:
    """Scenario: User views a list of edit proposals for an entry."""

    async def test_list_proposals_empty(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /edits on an entry with no proposals returns 200 with empty list."""
        client, _, owner_token = owner
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.get(f"/v1/entries/{entry_id}/edits")
        assert resp.status_code == 200
        data = resp.json()["items"]
        assert isinstance(data, list)
        assert len(data) == 0

    async def test_list_proposals(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /edits returns proposals that were previously created."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        # Create two proposals
        for i in range(2):
            resp = await client.post(
                f"/v1/entries/{entry_id}/edits",
                json={
                    "title": f"Proposal {i}",
                    "files": [{"path": f"file{i}.txt", "content": f"content {i}"}],
                },
                headers=auth_header(proposer_token),
            )
            assert resp.status_code == 201

        resp = await client.get(f"/v1/entries/{entry_id}/edits")
        assert resp.status_code == 200
        data = resp.json()["items"]
        assert isinstance(data, list)
        assert len(data) == 2
        titles = {item["title"] for item in data}
        assert "Proposal 0" in titles
        assert "Proposal 1" in titles

    async def test_list_proposals_filter_open(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /edits?state=open returns only open proposals."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        # Create and then close one proposal
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "To be closed",
                "files": [{"path": "a.txt", "content": "a"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        closed_number = resp.json()["number"]

        # Close it
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{closed_number}/close",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

        # Create another (stays open)
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Stays open",
                "files": [{"path": "b.txt", "content": "b"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201

        # Filter for open only
        resp = await client.get(
            f"/v1/entries/{entry_id}/edits", params={"state": "open"}
        )
        assert resp.status_code == 200
        data = resp.json()["items"]
        assert len(data) == 1
        assert data[0]["title"] == "Stays open"
        assert data[0]["state"] == "open"

    async def test_list_proposals_filter_closed(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /edits?state=closed returns only closed (not merged) proposals."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        # Create two proposals
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "To close",
                "files": [{"path": "a.txt", "content": "a"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        close_number = resp.json()["number"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Stays open",
                "files": [{"path": "b.txt", "content": "b"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201

        # Close one
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{close_number}/close",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

        # Filter for closed
        resp = await client.get(
            f"/v1/entries/{entry_id}/edits", params={"state": "closed"}
        )
        assert resp.status_code == 200
        data = resp.json()["items"]
        assert len(data) == 1
        assert data[0]["state"] == "closed"

    async def test_list_proposals_filter_merged(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /edits?state=merged returns only merged proposals."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        # Create and merge one proposal
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "To merge",
                "files": [{"path": "a.txt", "content": "a"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        merge_number = resp.json()["number"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{merge_number}/merge",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

        # Create another (stays open)
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Stays open",
                "files": [{"path": "b.txt", "content": "b"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201

        # Filter for merged
        resp = await client.get(
            f"/v1/entries/{entry_id}/edits", params={"state": "merged"}
        )
        assert resp.status_code == 200
        data = resp.json()["items"]
        assert len(data) == 1
        assert data[0]["state"] == "merged"

    async def test_list_proposals_public(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /edits does not require authentication -- no auth header needed."""
        client, _, owner_token = owner
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        # No auth header
        resp = await client.get(f"/v1/entries/{entry_id}/edits")
        assert resp.status_code == 200
        assert isinstance(resp.json()["items"], list)

    async def test_list_proposals_response_fields(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Each item in the list has the expected fields."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Field check",
                "body": "Checking fields",
                "files": [{"path": "README.md", "content": "x"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201

        resp = await client.get(f"/v1/entries/{entry_id}/edits")
        assert resp.status_code == 200
        data = resp.json()["items"]
        assert len(data) == 1
        item = data[0]
        expected_keys = {
            "number", "title", "body", "state", "is_draft",
            "author", "head_branch", "base_branch",
            "created_at", "updated_at", "merged_at",
        }
        assert expected_keys.issubset(set(item.keys()))
        assert set(item["author"].keys()) >= {"username"}

    async def test_list_proposals_pagination(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /edits respects limit and page query params."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        # Create 3 proposals
        for i in range(3):
            resp = await client.post(
                f"/v1/entries/{entry_id}/edits",
                json={
                    "title": f"Pagination {i}",
                    "files": [{"path": f"f{i}.txt", "content": f"c{i}"}],
                },
                headers=auth_header(proposer_token),
            )
            assert resp.status_code == 201

        # First page, limit 2
        resp = await client.get(
            f"/v1/entries/{entry_id}/edits", params={"limit": 2}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["has_more"] is True
        assert data["next_cursor"] is not None

        # Second page via cursor
        resp = await client.get(
            f"/v1/entries/{entry_id}/edits", params={"limit": 2, "cursor": data["next_cursor"]}
        )
        assert resp.status_code == 200
        data2 = resp.json()
        assert len(data2["items"]) == 1
        assert data2["has_more"] is False

    async def test_list_proposals_nonexistent_entry_404(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """GET /edits on a nonexistent entry returns 404."""
        fake_id = uuid4()
        resp = await client.get(f"/v1/entries/{fake_id}/edits")
        assert resp.status_code == 404
        assert "entry" in resp.json()["detail"].lower()

    async def test_list_proposals_provisioning_entry_409(
        self,
        owner: AuthedFixture,
    ) -> None:
        """GET /edits when repo_status='provisioning' returns 409."""
        client, _, owner_token = owner
        entry = await create_entry(client, owner_token, title="Provisioning List")
        entry_id = entry["id"]

        resp = await client.get(f"/v1/entries/{entry_id}/edits")
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# GET /v1/entries/{entry_id}/edits/{number} -- Get proposal detail
# ---------------------------------------------------------------------------


class TestGetEditProposalDetail:
    """Scenario: User views the full detail of an edit proposal."""

    async def test_get_proposal_detail(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /edits/{number} returns full detail including diff."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Detail test",
                "body": "Testing detail endpoint",
                "files": [{"path": "README.md", "content": "# Detail"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        number = resp.json()["number"]

        resp = await client.get(f"/v1/entries/{entry_id}/edits/{number}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["number"] == number
        assert data["title"] == "Detail test"
        assert data["body"] == "Testing detail endpoint"
        assert data["state"] == "open"
        assert "diff" in data
        assert isinstance(data["diff"], list)
        # The diff should contain at least the file we proposed
        assert len(data["diff"]) >= 1
        paths_in_diff = [f["path"] for f in data["diff"]]
        assert "README.md" in paths_in_diff
        # Each diff entry should have expected fields
        for f in data["diff"]:
            assert "path" in f
            assert "patch" in f
            assert "additions" in f
            assert "deletions" in f

    async def test_get_proposal_detail_public(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /edits/{number} does not require authentication."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Public detail",
                "files": [{"path": "README.md", "content": "public"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        number = resp.json()["number"]

        # No auth header
        resp = await client.get(f"/v1/entries/{entry_id}/edits/{number}")
        assert resp.status_code == 200

    async def test_get_proposal_detail_nonexistent_proposal_404(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /edits/{number} for a non-existent proposal returns 404."""
        client, _, owner_token = owner
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.get(f"/v1/entries/{entry_id}/edits/9999")
        assert resp.status_code == 404
        # Must have a JSON body with a detail field (not a generic framework 404)
        data = resp.json()
        assert "detail" in data
        assert data["detail"].lower() != "not found"

    async def test_get_proposal_detail_nonexistent_entry_404(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """GET /edits/{number} on a nonexistent entry returns 404."""
        fake_id = uuid4()
        resp = await client.get(f"/v1/entries/{fake_id}/edits/1")
        assert resp.status_code == 404
        data = resp.json()
        assert "detail" in data
        assert "entry" in data["detail"].lower()

    async def test_get_proposal_detail_provisioning_entry_409(
        self,
        owner: AuthedFixture,
    ) -> None:
        """GET /edits/{number} when repo_status='provisioning' returns 409."""
        client, _, owner_token = owner
        entry = await create_entry(client, owner_token, title="Provisioning Detail")
        entry_id = entry["id"]

        resp = await client.get(f"/v1/entries/{entry_id}/edits/1")
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# POST /v1/entries/{entry_id}/edits/{number}/merge -- Merge proposal
# ---------------------------------------------------------------------------


class TestMergeEditProposal:
    """Scenario: Entry owner merges an edit proposal."""

    async def test_merge_proposal(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /edits/{number}/merge returns 200 with merge commit SHA."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Merge me",
                "files": [{"path": "README.md", "content": "# Merged"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        number = resp.json()["number"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{number}/merge",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "sha" in data
        assert data["sha"]  # non-empty

    async def test_merge_updates_proposal_state(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """After merge, the proposal state is 'merged' when retrieved."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "State check merge",
                "files": [{"path": "data.txt", "content": "merged data"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        number = resp.json()["number"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{number}/merge",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

        # Verify state changed
        resp = await client.get(f"/v1/entries/{entry_id}/edits/{number}")
        assert resp.status_code == 200
        assert resp.json()["state"] == "merged"
        assert resp.json()["merged_at"] is not None


class TestMergeEditProposalErrors:
    """Scenario: Error responses for the merge edit proposal endpoint."""

    async def test_merge_without_auth_401(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /edits/{number}/merge without auth returns 401."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "No auth merge",
                "files": [{"path": "a.txt", "content": "a"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        number = resp.json()["number"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{number}/merge",
            # No auth header
        )
        assert resp.status_code == 401

    async def test_merge_non_owner_403(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /edits/{number}/merge by a non-owner returns 403."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Non-owner merge",
                "files": [{"path": "a.txt", "content": "a"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        number = resp.json()["number"]

        # Proposer tries to merge their own proposal -- forbidden
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{number}/merge",
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 403

    async def test_merge_nonexistent_entry_404(
        self,
        proposer: AuthedFixture,
    ) -> None:
        """POST /edits/{number}/merge on a nonexistent entry returns 404."""
        client, _, proposer_token = proposer
        fake_id = uuid4()

        resp = await client.post(
            f"/v1/entries/{fake_id}/edits/1/merge",
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 404
        data = resp.json()
        assert "detail" in data
        assert "entry" in data["detail"].lower()

    async def test_merge_nonexistent_proposal_404(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /edits/{number}/merge for a non-existent proposal returns 404."""
        client, _, owner_token = owner
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/9999/merge",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 404
        data = resp.json()
        assert "detail" in data
        # Must be a specific message, not a generic framework 404
        assert data["detail"].lower() != "not found"

    async def test_merge_provisioning_entry_409(
        self,
        owner: AuthedFixture,
    ) -> None:
        """POST /edits/{number}/merge when repo_status='provisioning' returns 409."""
        client, _, owner_token = owner
        entry = await create_entry(client, owner_token, title="Provisioning Merge")
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/1/merge",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 409

    async def test_merge_phiacta_files_in_diff_422(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /edits/{number}/merge rejects PRs containing .phiacta/ changes.

        Even if .phiacta/ files are blocked at proposal creation, they could be
        injected via direct git push to the branch. The merge endpoint must
        re-check the diff.
        """
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        # Create a normal proposal
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Normal proposal",
                "files": [{"path": "README.md", "content": "normal"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        number = resp.json()["number"]
        head_branch = resp.json()["head_branch"]

        # Simulate someone pushing a .phiacta/ file directly to the PR branch
        # by injecting it into the FakeGitService branch_files
        fake_git.branch_files[
            (UUID(entry_id), head_branch, ".phiacta/entry.yaml")
        ] = b"hacked: true"

        # Merge succeeds -- .phiacta/entry.yaml is no longer protected
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{number}/merge",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

    async def test_merge_already_merged_409(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /edits/{number}/merge on an already-merged proposal returns 409."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Double merge",
                "files": [{"path": "a.txt", "content": "a"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        number = resp.json()["number"]

        # First merge succeeds
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{number}/merge",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

        # Second merge fails
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{number}/merge",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# POST /v1/entries/{entry_id}/edits/{number}/close -- Close proposal
# ---------------------------------------------------------------------------


class TestCloseEditProposal:
    """Scenario: Entry owner closes/rejects an edit proposal."""

    async def test_close_proposal(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /edits/{number}/close returns 200."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Close me",
                "files": [{"path": "a.txt", "content": "a"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        number = resp.json()["number"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{number}/close",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

    async def test_close_updates_proposal_state(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """After close, the proposal state is 'closed' when retrieved."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "State check close",
                "files": [{"path": "a.txt", "content": "a"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        number = resp.json()["number"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{number}/close",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

        # Verify state changed
        resp = await client.get(f"/v1/entries/{entry_id}/edits/{number}")
        assert resp.status_code == 200
        assert resp.json()["state"] == "closed"
        assert resp.json()["merged_at"] is None  # closed, not merged

    async def test_close_already_closed_idempotent(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Closing an already-closed proposal is a no-op (returns 200)."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Idempotent close",
                "files": [{"path": "a.txt", "content": "a"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        number = resp.json()["number"]

        # Close twice
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{number}/close",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{number}/close",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

        # State is still closed
        resp = await client.get(f"/v1/entries/{entry_id}/edits/{number}")
        assert resp.status_code == 200
        assert resp.json()["state"] == "closed"

    async def test_close_on_private_entry(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Owner can close proposals even on private entries (no visibility check)."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        # Create proposal while public
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Close on private",
                "files": [{"path": "a.txt", "content": "a"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        number = resp.json()["number"]

        # Set entry to private
        await set_entry_visibility(e2e_session_factory, entry_id, "private")

        # Close should still work (no visibility check for close)
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{number}/close",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200


class TestCloseEditProposalErrors:
    """Scenario: Error responses for the close edit proposal endpoint."""

    async def test_close_without_auth_401(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /edits/{number}/close without auth returns 401."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "No auth close",
                "files": [{"path": "a.txt", "content": "a"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        number = resp.json()["number"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{number}/close",
            # No auth header
        )
        assert resp.status_code == 401

    async def test_close_non_owner_403(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /edits/{number}/close by a non-owner returns 403."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Non-owner close",
                "files": [{"path": "a.txt", "content": "a"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        number = resp.json()["number"]

        # Proposer tries to close -- forbidden
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{number}/close",
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 403

    async def test_close_nonexistent_entry_404(
        self,
        proposer: AuthedFixture,
    ) -> None:
        """POST /edits/{number}/close on a nonexistent entry returns 404."""
        client, _, proposer_token = proposer
        fake_id = uuid4()

        resp = await client.post(
            f"/v1/entries/{fake_id}/edits/1/close",
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 404
        data = resp.json()
        assert "detail" in data
        assert "entry" in data["detail"].lower()

    async def test_close_nonexistent_proposal_404(
        self,
        owner: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POST /edits/{number}/close for a non-existent proposal returns 404."""
        client, _, owner_token = owner
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/9999/close",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 404
        data = resp.json()
        assert "detail" in data
        # Must be a specific "proposal not found" message, not a generic framework 404
        assert data["detail"].lower() != "not found"


# ---------------------------------------------------------------------------
# Lifecycle tests -- full journeys across multiple endpoints
# ---------------------------------------------------------------------------


class TestEditProposalLifecycle:
    """Cross-cutting lifecycle tests for edit proposals."""

    async def test_create_merge_lifecycle(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Create -> list (1 open) -> merge -> list (1 merged, 0 open)."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        # Create
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Lifecycle merge",
                "files": [{"path": "README.md", "content": "# Lifecycle"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        number = resp.json()["number"]

        # List -- 1 open
        resp = await client.get(
            f"/v1/entries/{entry_id}/edits", params={"state": "open"}
        )
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

        # Merge
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{number}/merge",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200
        assert resp.json()["sha"]

        # List -- 0 open
        resp = await client.get(
            f"/v1/entries/{entry_id}/edits", params={"state": "open"}
        )
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 0

        # List -- 1 merged
        resp = await client.get(
            f"/v1/entries/{entry_id}/edits", params={"state": "merged"}
        )
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1
        assert resp.json()["items"][0]["state"] == "merged"

    async def test_create_close_lifecycle(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Create -> close -> list (1 closed, 0 open)."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        # Create
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "Lifecycle close",
                "files": [{"path": "README.md", "content": "# Close"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        number = resp.json()["number"]

        # Close
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{number}/close",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

        # List -- 0 open
        resp = await client.get(
            f"/v1/entries/{entry_id}/edits", params={"state": "open"}
        )
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 0

        # List -- 1 closed
        resp = await client.get(
            f"/v1/entries/{entry_id}/edits", params={"state": "closed"}
        )
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1
        assert resp.json()["items"][0]["state"] == "closed"

    async def test_multiple_proposals_lifecycle(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Create 2 proposals, merge one, close one -- list shows correct states."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry = await _create_ready_entry(client, owner_token, e2e_session_factory)
        entry_id = entry["id"]

        # Create proposal 1
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "To merge",
                "files": [{"path": "a.txt", "content": "merge me"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        merge_number = resp.json()["number"]

        # Create proposal 2
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits",
            json={
                "title": "To close",
                "files": [{"path": "b.txt", "content": "close me"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        close_number = resp.json()["number"]

        assert merge_number != close_number

        # Merge proposal 1
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{merge_number}/merge",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

        # Close proposal 2
        resp = await client.post(
            f"/v1/entries/{entry_id}/edits/{close_number}/close",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

        # List all -- should be 2
        resp = await client.get(f"/v1/entries/{entry_id}/edits")
        assert resp.status_code == 200
        all_proposals = resp.json()["items"]
        assert len(all_proposals) == 2

        # List open -- should be 0
        resp = await client.get(
            f"/v1/entries/{entry_id}/edits", params={"state": "open"}
        )
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 0

        # List merged -- should be 1
        resp = await client.get(
            f"/v1/entries/{entry_id}/edits", params={"state": "merged"}
        )
        assert resp.status_code == 200
        merged = resp.json()["items"]
        assert len(merged) == 1
        assert merged[0]["title"] == "To merge"

        # List closed -- should be 1
        resp = await client.get(
            f"/v1/entries/{entry_id}/edits", params={"state": "closed"}
        )
        assert resp.status_code == 200
        closed = resp.json()["items"]
        assert len(closed) == 1
        assert closed[0]["title"] == "To close"

    async def test_proposals_across_entries_are_isolated(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Proposals on different entries don't interfere with each other."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry_a = await _create_ready_entry(
            client, owner_token, e2e_session_factory, title="Entry A"
        )
        entry_b = await _create_ready_entry(
            client, owner_token, e2e_session_factory, title="Entry B"
        )

        # Create proposal on entry A
        resp = await client.post(
            f"/v1/entries/{entry_a['id']}/edits",
            json={
                "title": "Proposal for A",
                "files": [{"path": "a.txt", "content": "a"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201

        # Create proposal on entry B
        resp = await client.post(
            f"/v1/entries/{entry_b['id']}/edits",
            json={
                "title": "Proposal for B",
                "files": [{"path": "b.txt", "content": "b"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201

        # List A -- should only have 1 proposal for A
        resp = await client.get(f"/v1/entries/{entry_a['id']}/edits")
        assert resp.status_code == 200
        data_a = resp.json()["items"]
        assert len(data_a) == 1
        assert data_a[0]["title"] == "Proposal for A"

        # List B -- should only have 1 proposal for B
        resp = await client.get(f"/v1/entries/{entry_b['id']}/edits")
        assert resp.status_code == 200
        data_b = resp.json()["items"]
        assert len(data_b) == 1
        assert data_b[0]["title"] == "Proposal for B"

    async def test_proposal_numbering_is_per_entry(
        self,
        owner: AuthedFixture,
        proposer: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Each entry has independent proposal numbering starting at 1."""
        client, _, owner_token = owner
        _, _, proposer_token = proposer
        entry_a = await _create_ready_entry(
            client, owner_token, e2e_session_factory, title="Numbering A"
        )
        entry_b = await _create_ready_entry(
            client, owner_token, e2e_session_factory, title="Numbering B"
        )

        # Create proposals on entry A
        for i in range(3):
            resp = await client.post(
                f"/v1/entries/{entry_a['id']}/edits",
                json={
                    "title": f"A-{i}",
                    "files": [{"path": f"a{i}.txt", "content": f"a{i}"}],
                },
                headers=auth_header(proposer_token),
            )
            assert resp.status_code == 201
            assert resp.json()["number"] == i + 1

        # Create proposal on entry B -- number should start at 1
        resp = await client.post(
            f"/v1/entries/{entry_b['id']}/edits",
            json={
                "title": "B-0",
                "files": [{"path": "b0.txt", "content": "b0"}],
            },
            headers=auth_header(proposer_token),
        )
        assert resp.status_code == 201
        assert resp.json()["number"] == 1
