# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for entry history API (NEV-127).

Tests the full API contract for:
- GET /v1/entries/{entry_id}/history  -- paginated commit log
- GET /v1/entries/{entry_id}/history/{sha}  -- diff for a specific commit

These endpoints are public (no auth required).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from phiacta.core.services.git_service import AuthorInfo, CommitInfo, DiffInfo, FileDiff
from tests.e2e.conftest import (
    FakeGitService,
    create_entry,
    register_user,
    set_entry_repo_status,
)

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    """Register a user and return (client, user_data, token)."""
    uid = uuid4().hex[:8]
    auth = await register_user(
        client, handle=f"hist-{uid}"
    )
    return client, auth["user"], auth["access_token"]


# ---------------------------------------------------------------------------
# GET /v1/entries/{entry_id}/history -- Paginated commit log
# ---------------------------------------------------------------------------


class TestListCommits:
    """Scenario: User views an entry's commit history."""

    async def test_list_commits_returns_commits(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /history returns 200 with commit list."""
        client, _, token = authed
        entry = await create_entry(client, token, title="History Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        ts = datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)
        fake_git.commit_history[UUID(entry_id)] = [
            CommitInfo(
                sha="abc123def456",
                message="Initial commit",
                author=AuthorInfo(name="test-user", email="test@phiacta.local"),
                timestamp=ts,
            ),
        ]

        resp = await client.get(f"/v1/entries/{entry_id}/history")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["sha"] == "abc123def456"
        assert data[0]["message"] == "Initial commit"
        assert data[0]["author"]["name"] == "test-user"

    async def test_list_commits_multiple_commits(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /history returns multiple commits in order."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Multi Commit Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        ts1 = datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)
        ts2 = datetime(2026, 3, 15, 13, 0, 0, tzinfo=UTC)
        fake_git.commit_history[UUID(entry_id)] = [
            CommitInfo(
                sha="sha_second",
                message="Second commit",
                author=AuthorInfo(name="user", email="user@phiacta.local"),
                timestamp=ts2,
            ),
            CommitInfo(
                sha="sha_first",
                message="First commit",
                author=AuthorInfo(name="user", email="user@phiacta.local"),
                timestamp=ts1,
            ),
        ]

        resp = await client.get(f"/v1/entries/{entry_id}/history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["sha"] == "sha_second"
        assert data[1]["sha"] == "sha_first"

    async def test_list_commits_is_public(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /history does not require authentication."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Public History Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        fake_git.commit_history[UUID(entry_id)] = []

        # No auth header
        resp = await client.get(f"/v1/entries/{entry_id}/history")
        assert resp.status_code == 200

    async def test_list_commits_empty_history(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /history on repo with no commits returns 200 with []."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Empty History Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        fake_git.commit_history[UUID(entry_id)] = []

        resp = await client.get(f"/v1/entries/{entry_id}/history")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_commits_pagination(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /history respects limit and page query params."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Paginated History")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        ts = datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)
        commits = [
            CommitInfo(
                sha=f"sha_{i:04d}",
                message=f"Commit {i}",
                author=AuthorInfo(name="user", email="user@phiacta.local"),
                timestamp=ts,
            )
            for i in range(5)
        ]
        fake_git.commit_history[UUID(entry_id)] = commits

        # Page 1, limit 2
        resp = await client.get(
            f"/v1/entries/{entry_id}/history", params={"limit": 2, "page": 1}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["sha"] == "sha_0000"
        assert data[1]["sha"] == "sha_0001"

        # Page 2, limit 2
        resp = await client.get(
            f"/v1/entries/{entry_id}/history", params={"limit": 2, "page": 2}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["sha"] == "sha_0002"

    async def test_list_commits_response_has_expected_fields(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Each commit item has sha, message, author {name, email}, timestamp."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Fields Check History")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        ts = datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)
        fake_git.commit_history[UUID(entry_id)] = [
            CommitInfo(
                sha="abc123",
                message="Test commit",
                author=AuthorInfo(name="alice", email="alice@phiacta.local"),
                timestamp=ts,
            ),
        ]

        resp = await client.get(f"/v1/entries/{entry_id}/history")
        assert resp.status_code == 200
        item = resp.json()[0]
        assert set(item.keys()) == {"sha", "message", "author", "timestamp"}
        assert set(item["author"].keys()) == {"name", "email"}
        assert item["author"]["name"] == "alice"
        assert item["author"]["email"] == "alice@phiacta.local"


class TestListCommitsErrors:
    """Scenario: Error responses for the commit list endpoint."""

    async def test_list_commits_nonexistent_entry_returns_404(
        self, client: httpx.AsyncClient
    ) -> None:
        """GET /history with a nonexistent UUID returns 404."""
        fake_id = uuid4()
        resp = await client.get(f"/v1/entries/{fake_id}/history")
        assert resp.status_code == 404
        assert "entry" in resp.json()["detail"].lower()

    async def test_list_commits_invalid_uuid_returns_422(
        self, client: httpx.AsyncClient
    ) -> None:
        """GET /history with an invalid UUID returns 422."""
        resp = await client.get("/v1/entries/not-a-uuid/history")
        assert resp.status_code == 422

    async def test_list_commits_repo_provisioning_returns_409(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Entry with repo_status='provisioning' returns 409."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Provisioning History")
        entry_id = entry["id"]

        resp = await client.get(f"/v1/entries/{entry_id}/history")
        assert resp.status_code == 409
        assert "not yet ready" in resp.json()["detail"].lower()

    async def test_list_commits_repo_error_returns_409(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Entry with repo_status='error' returns 409."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Error History")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "error")

        resp = await client.get(f"/v1/entries/{entry_id}/history")
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# GET /v1/entries/{entry_id}/history/{sha} -- Commit diff
# ---------------------------------------------------------------------------


class TestGetCommitDiff:
    """Scenario: User views the diff for a specific commit."""

    async def test_get_diff_returns_diff(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /history/{sha} returns 200 with diff details."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Diff Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        sha_parent = "a" * 40
        sha_head = "b" * 40
        diff = DiffInfo(
            base_sha=sha_parent,
            head_sha=sha_head,
            files_changed=[
                FileDiff(
                    path="README.md",
                    patch="@@ -1 +1 @@\n-old\n+new",
                    additions=1,
                    deletions=1,
                ),
            ],
        )
        # Store with sha~1 as base (the convention the endpoint will use)
        fake_git.diffs[(UUID(entry_id), f"{sha_head}~1", sha_head)] = diff

        resp = await client.get(f"/v1/entries/{entry_id}/history/{sha_head}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["base_sha"] == sha_parent
        assert data["head_sha"] == sha_head
        assert len(data["files_changed"]) == 1
        assert data["files_changed"][0]["path"] == "README.md"
        assert data["files_changed"][0]["additions"] == 1
        assert data["files_changed"][0]["deletions"] == 1

    async def test_get_diff_multiple_files_changed(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /history/{sha} returns multiple changed files."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Multi Diff Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        sha_parent = "c" * 40
        sha_head = "d" * 40
        diff = DiffInfo(
            base_sha=sha_parent,
            head_sha=sha_head,
            files_changed=[
                FileDiff(path="README.md", patch="diff1", additions=5, deletions=2),
                FileDiff(path="data.csv", patch="diff2", additions=100, deletions=0),
            ],
        )
        fake_git.diffs[(UUID(entry_id), f"{sha_head}~1", sha_head)] = diff

        resp = await client.get(f"/v1/entries/{entry_id}/history/{sha_head}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["files_changed"]) == 2
        paths = [f["path"] for f in data["files_changed"]]
        assert "README.md" in paths
        assert "data.csv" in paths

    async def test_get_diff_is_public(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /history/{sha} does not require authentication."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Public Diff Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        sha_parent = "e" * 40
        sha_head = "f" * 40
        fake_git.diffs[(UUID(entry_id), f"{sha_head}~1", sha_head)] = DiffInfo(
            base_sha=sha_parent, head_sha=sha_head, files_changed=[],
        )

        # No auth header
        resp = await client.get(f"/v1/entries/{entry_id}/history/{sha_head}")
        assert resp.status_code == 200

    async def test_get_diff_response_has_expected_fields(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Response has base_sha, head_sha, files_changed with expected fields."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Fields Diff Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        sha_parent = "0" * 40
        sha_head = "1" * 40
        fake_git.diffs[(UUID(entry_id), f"{sha_head}~1", sha_head)] = DiffInfo(
            base_sha=sha_parent,
            head_sha=sha_head,
            files_changed=[
                FileDiff(path="f.py", patch="p", additions=1, deletions=0),
            ],
        )

        resp = await client.get(f"/v1/entries/{entry_id}/history/{sha_head}")
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == {"base_sha", "head_sha", "files_changed"}
        f = data["files_changed"][0]
        assert set(f.keys()) == {"path", "patch", "additions", "deletions"}


class TestGetCommitDiffErrors:
    """Scenario: Error responses for the commit diff endpoint."""

    async def test_get_diff_nonexistent_entry_returns_404(
        self, client: httpx.AsyncClient
    ) -> None:
        """GET /history/{sha} with nonexistent entry returns 404."""
        fake_id = uuid4()
        sha = "a" * 40
        resp = await client.get(f"/v1/entries/{fake_id}/history/{sha}")
        assert resp.status_code == 404
        assert "entry" in resp.json()["detail"].lower()

    async def test_get_diff_nonexistent_sha_returns_404(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /history/{sha} with unknown SHA returns 404."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Missing SHA Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # Don't populate any diffs -- use a valid-format SHA that has no data
        sha = "2" * 40
        resp = await client.get(f"/v1/entries/{entry_id}/history/{sha}")
        assert resp.status_code == 404

    async def test_get_diff_invalid_uuid_returns_422(
        self, client: httpx.AsyncClient
    ) -> None:
        """GET /history/{sha} with invalid UUID returns 422."""
        sha = "4" * 40
        resp = await client.get(f"/v1/entries/not-a-uuid/history/{sha}")
        assert resp.status_code == 422

    async def test_get_diff_repo_provisioning_returns_409(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Entry with repo_status='provisioning' returns 409."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Provisioning Diff")
        entry_id = entry["id"]

        sha = "3" * 40
        resp = await client.get(f"/v1/entries/{entry_id}/history/{sha}")
        assert resp.status_code == 409
