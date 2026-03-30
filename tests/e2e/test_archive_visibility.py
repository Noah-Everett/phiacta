# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for archive visibility rules.

Tests that archived entries are only visible to their owner. Non-owners
(including unauthenticated requests) must receive 404 for:
- Graph traversal results
- Sub-resource access (files, history, edits, issues)
- Entity resolve
- References list on archived entries

These tests complement the existing archival tests in test_entry_archival.py,
test_search_filters.py, and test_extension_tags.py by covering the remaining
visibility gaps specified in the archive visibility feature spec.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import phiacta.extensions.metadata.models  # noqa: F401
import phiacta.extensions.references.models  # noqa: F401
import phiacta.extensions.tags.models  # noqa: F401
import phiacta.extensions.types.models  # noqa: F401

from phiacta.core.services.git_service import AuthorInfo, CommitInfo, DiffInfo, FileDiff
from tests.e2e.conftest import (
    FakeGitService,
    auth_header,
    create_entry,
    register_user,
    set_entry_repo_status,
    set_entry_status,
)

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


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
    """Register the entry owner and return (client, user_data, token)."""
    auth = await register_user(client, handle=f"archvis-owner-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def other_user(client: httpx.AsyncClient) -> AuthedFixture:
    """Register a non-owner user and return (client, user_data, token)."""
    auth = await register_user(client, handle=f"archvis-other-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def archived_entry(
    owner: AuthedFixture,
    e2e_session_factory: async_sessionmaker[AsyncSession],
    fake_git: FakeGitService,
) -> tuple[AuthedFixture, dict]:
    """Create an entry, set it to ready, then archive it.

    Also populates the FakeGitService with minimal file data so sub-resource
    endpoints have something to return for the owner.
    """
    client, _, token = owner
    entry = await create_entry(
        client, token, title="Archived Visibility Test Entry",
        summary="An entry that will be archived for visibility testing",
    )
    entry_id = entry["id"]
    await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

    # Populate fake git with file data so the owner CAN access sub-resources
    eid = UUID(entry_id)
    fake_git.files[(eid, ".phiacta/content.md")] = b"# Test Content\nSome text."
    fake_git.files[(eid, ".phiacta/entry.yaml")] = b"id: test\nformat: markdown"

    # Populate commit history
    ts = datetime(2026, 3, 20, 12, 0, 0, tzinfo=UTC)
    fake_git.commit_history[eid] = [
        CommitInfo(
            sha="aabbcc1122334455667788990011223344556677",
            message="Initial commit",
            author=AuthorInfo(name="archvis-owner", email="owner@phiacta.local"),
            timestamp=ts,
        ),
    ]

    # Populate a diff for the commit
    fake_git.diffs[(eid, "aabbcc1122334455667788990011223344556677~1", "aabbcc1122334455667788990011223344556677")] = DiffInfo(
        base_sha="0" * 40,
        head_sha="aabbcc1122334455667788990011223344556677",
        files_changed=[
            FileDiff(path=".phiacta/content.md", patch="@@ +1 @@\n+content", additions=1, deletions=0),
        ],
    )

    # Create an edit proposal (PR) via the fake git
    await fake_git.create_pull_request(
        eid,
        title="Fix typo",
        body="Corrects a spelling error",
        head_branch="edit/fix-typo",
        author_name="proposer",
    )

    # Create an issue via the fake git
    await fake_git.create_issue(
        eid,
        title="Found a bug",
        body="Something is wrong",
        author_name="reporter",
    )

    # Archive the entry
    await set_entry_status(e2e_session_factory, entry_id, "archived")

    return owner, entry


# ===========================================================================
# 1. Graph Traversal — Archived entries excluded for non-owners
# ===========================================================================


class TestGraphArchivedVisibility:
    """Scenario: Non-owners must not see archived entries in graph results.

    The graph tool traverses references between entries. Archived entries
    should be invisible to non-owners: they must not appear as nodes,
    their edges must be excluded, and using one as a seed should silently
    exclude it.
    """

    async def test_archived_seed_excluded_for_non_owner(
        self,
        archived_entry: tuple[AuthedFixture, dict],
        other_user: AuthedFixture,
    ) -> None:
        """An archived entry used as a seed is silently excluded for non-owners.

        The graph should return an empty result (no nodes, no edges) rather
        than an error, since the archived entry behaves as if it doesn't exist.
        """
        (_, _, _), entry = archived_entry
        client, _, other_token = other_user

        # Non-owner queries graph with archived entry as seed
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": entry["id"], "depth": 2},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        node_ids = {n["id"] for n in data["nodes"]}
        assert entry["id"] not in node_ids

    async def test_archived_seed_excluded_for_unauthenticated(
        self,
        archived_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Unauthenticated users also cannot see archived seeds."""
        (client, _, _), entry = archived_entry

        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": entry["id"], "depth": 2},
        )
        assert resp.status_code == 200
        data = resp.json()
        node_ids = {n["id"] for n in data["nodes"]}
        assert entry["id"] not in node_ids

    async def test_archived_neighbor_excluded_during_traversal(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """An archived entry discovered during BFS traversal is skipped.

        Setup: A -> B -> C, where B is archived.
        Non-owner starts from A with depth=2. B should be excluded, and
        therefore C (only reachable through B) should also be excluded.
        """
        client, _, owner_token = owner

        entry_a = await create_entry(client, owner_token, title="Graph Active A")
        entry_b = await create_entry(client, owner_token, title="Graph Archived B")
        entry_c = await create_entry(client, owner_token, title="Graph Active C")

        for e in (entry_a, entry_b, entry_c):
            await set_entry_repo_status(e2e_session_factory, e["id"], "ready")

        # A -> B (supports)
        resp = await client.post(
            f"/v1/extensions/references/{entry_a['id']}",
            json={"target_entry_id": entry_b["id"], "rel": "supports"},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 201

        # B -> C (cites)
        resp = await client.post(
            f"/v1/extensions/references/{entry_b['id']}",
            json={"target_entry_id": entry_c["id"], "rel": "cites"},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 201

        # Archive B
        await set_entry_status(e2e_session_factory, entry_b["id"], "archived")

        # Non-owner traverses from A
        _, _, other_token = other_user
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": entry_a["id"], "depth": 2},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        node_ids = {n["id"] for n in data["nodes"]}

        # A should be present (active seed), B should be absent (archived)
        assert entry_a["id"] in node_ids
        assert entry_b["id"] not in node_ids
        # C is unreachable because B (the path) is archived
        assert entry_c["id"] not in node_ids

    async def test_edges_to_archived_excluded_for_non_owner(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Edges connecting to an archived entry are excluded for non-owners.

        Setup: A -> B, where B is archived.
        Non-owner queries graph from A. The edge A->B must not appear.
        """
        client, _, owner_token = owner

        entry_a = await create_entry(client, owner_token, title="Edge Active A")
        entry_b = await create_entry(client, owner_token, title="Edge Archived B")

        for e in (entry_a, entry_b):
            await set_entry_repo_status(e2e_session_factory, e["id"], "ready")

        resp = await client.post(
            f"/v1/extensions/references/{entry_a['id']}",
            json={"target_entry_id": entry_b["id"], "rel": "supports"},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 201

        # Archive B
        await set_entry_status(e2e_session_factory, entry_b["id"], "archived")

        # Non-owner queries from A
        _, _, other_token = other_user
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": entry_a["id"], "depth": 1},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 200
        data = resp.json()

        # No edges should reference B
        for edge in data["edges"]:
            assert edge["source"] != entry_b["id"]
            assert edge["target"] != entry_b["id"]

        # B should not appear as a node
        node_ids = {n["id"] for n in data["nodes"]}
        assert entry_b["id"] not in node_ids

    async def test_owner_sees_archived_entries_in_graph(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Owner CAN see their own archived entries in graph results.

        Setup: A -> B, where B is archived. Owner queries from A.
        Both A and B should appear, along with the edge.
        """
        client, _, owner_token = owner

        entry_a = await create_entry(client, owner_token, title="Owner Graph A")
        entry_b = await create_entry(client, owner_token, title="Owner Graph B")

        for e in (entry_a, entry_b):
            await set_entry_repo_status(e2e_session_factory, e["id"], "ready")

        resp = await client.post(
            f"/v1/extensions/references/{entry_a['id']}",
            json={"target_entry_id": entry_b["id"], "rel": "cites"},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 201

        # Archive B
        await set_entry_status(e2e_session_factory, entry_b["id"], "archived")

        # Owner queries from A — should see both
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

        # Edge A->B should be present
        assert len(data["edges"]) >= 1

    async def test_owner_can_use_archived_entry_as_seed(
        self,
        archived_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Owner CAN use their own archived entry as a graph seed."""
        (client, _, owner_token), entry = archived_entry

        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": entry["id"], "depth": 0},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        node_ids = {n["id"] for n in data["nodes"]}
        assert entry["id"] in node_ids

    async def test_mixed_seeds_archived_excluded_for_non_owner(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """When multiple seeds are given, archived ones are silently excluded.

        Non-owner passes both an active entry and an archived entry as seeds.
        Only the active entry should appear.
        """
        client, _, owner_token = owner

        active = await create_entry(client, owner_token, title="Mixed Active Seed")
        archived = await create_entry(client, owner_token, title="Mixed Archived Seed")
        for e in (active, archived):
            await set_entry_repo_status(e2e_session_factory, e["id"], "ready")

        await set_entry_status(e2e_session_factory, archived["id"], "archived")

        _, _, other_token = other_user
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": f"{active['id']},{archived['id']}", "depth": 0},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        node_ids = {n["id"] for n in data["nodes"]}
        assert active["id"] in node_ids
        assert archived["id"] not in node_ids


# ===========================================================================
# 2. Sub-resource access on archived entries
# ===========================================================================


class TestSubResourceFilesArchived:
    """Scenario: Non-owners cannot access files of archived entries."""

    async def test_list_files_returns_404_for_non_owner(
        self,
        archived_entry: tuple[AuthedFixture, dict],
        other_user: AuthedFixture,
    ) -> None:
        """GET /entries/{id}/files returns 404 for non-owners on archived entries."""
        (_, _, _), entry = archived_entry
        client, _, other_token = other_user

        resp = await client.get(
            f"/v1/entries/{entry['id']}/files",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 404

    async def test_list_files_returns_404_for_unauthenticated(
        self,
        archived_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """GET /entries/{id}/files returns 404 without auth on archived entries."""
        (client, _, _), entry = archived_entry

        resp = await client.get(f"/v1/entries/{entry['id']}/files")
        assert resp.status_code == 404

    async def test_read_file_returns_404_for_non_owner(
        self,
        archived_entry: tuple[AuthedFixture, dict],
        other_user: AuthedFixture,
    ) -> None:
        """GET /entries/{id}/files/.phiacta/content.md returns 404 for non-owners."""
        (_, _, _), entry = archived_entry
        client, _, other_token = other_user

        resp = await client.get(
            f"/v1/entries/{entry['id']}/files/.phiacta/content.md",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 404

    async def test_read_file_returns_404_for_unauthenticated(
        self,
        archived_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """GET /entries/{id}/files/.phiacta/content.md returns 404 without auth."""
        (client, _, _), entry = archived_entry

        resp = await client.get(
            f"/v1/entries/{entry['id']}/files/.phiacta/content.md",
        )
        assert resp.status_code == 404

    async def test_owner_can_list_files(
        self,
        archived_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Owner CAN list files on their own archived entry."""
        (client, _, owner_token), entry = archived_entry

        resp = await client.get(
            f"/v1/entries/{entry['id']}/files",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

    async def test_owner_can_read_file(
        self,
        archived_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Owner CAN read files on their own archived entry."""
        (client, _, owner_token), entry = archived_entry

        resp = await client.get(
            f"/v1/entries/{entry['id']}/files/.phiacta/content.md",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200


class TestSubResourceHistoryArchived:
    """Scenario: Non-owners cannot access history of archived entries."""

    async def test_list_history_returns_404_for_non_owner(
        self,
        archived_entry: tuple[AuthedFixture, dict],
        other_user: AuthedFixture,
    ) -> None:
        """GET /entries/{id}/history returns 404 for non-owners on archived entries."""
        (_, _, _), entry = archived_entry
        client, _, other_token = other_user

        resp = await client.get(
            f"/v1/entries/{entry['id']}/history",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 404

    async def test_list_history_returns_404_for_unauthenticated(
        self,
        archived_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """GET /entries/{id}/history returns 404 without auth on archived entries."""
        (client, _, _), entry = archived_entry

        resp = await client.get(f"/v1/entries/{entry['id']}/history")
        assert resp.status_code == 404

    async def test_owner_can_list_history(
        self,
        archived_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Owner CAN list commit history on their own archived entry."""
        (client, _, owner_token), entry = archived_entry

        resp = await client.get(
            f"/v1/entries/{entry['id']}/history",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

    async def test_get_commit_diff_returns_404_for_non_owner(
        self,
        archived_entry: tuple[AuthedFixture, dict],
        other_user: AuthedFixture,
    ) -> None:
        """GET /entries/{id}/history/{sha} returns 404 for non-owners."""
        (_, _, _), entry = archived_entry
        client, _, other_token = other_user
        sha = "aabbcc1122334455667788990011223344556677"

        resp = await client.get(
            f"/v1/entries/{entry['id']}/history/{sha}",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 404

    async def test_get_commit_diff_returns_404_for_unauthenticated(
        self,
        archived_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """GET /entries/{id}/history/{sha} returns 404 without auth."""
        (client, _, _), entry = archived_entry
        sha = "aabbcc1122334455667788990011223344556677"

        resp = await client.get(f"/v1/entries/{entry['id']}/history/{sha}")
        assert resp.status_code == 404


class TestSubResourceEditsArchived:
    """Scenario: Non-owners cannot access edit proposals of archived entries."""

    async def test_list_edits_returns_404_for_non_owner(
        self,
        archived_entry: tuple[AuthedFixture, dict],
        other_user: AuthedFixture,
    ) -> None:
        """GET /entries/{id}/edits returns 404 for non-owners on archived entries."""
        (_, _, _), entry = archived_entry
        client, _, other_token = other_user

        resp = await client.get(
            f"/v1/entries/{entry['id']}/edits",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 404

    async def test_list_edits_returns_404_for_unauthenticated(
        self,
        archived_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """GET /entries/{id}/edits returns 404 without auth on archived entries."""
        (client, _, _), entry = archived_entry

        resp = await client.get(f"/v1/entries/{entry['id']}/edits")
        assert resp.status_code == 404

    async def test_get_edit_detail_returns_404_for_non_owner(
        self,
        archived_entry: tuple[AuthedFixture, dict],
        other_user: AuthedFixture,
    ) -> None:
        """GET /entries/{id}/edits/{number} returns 404 for non-owners."""
        (_, _, _), entry = archived_entry
        client, _, other_token = other_user

        resp = await client.get(
            f"/v1/entries/{entry['id']}/edits/1",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 404

    async def test_get_edit_detail_returns_404_for_unauthenticated(
        self,
        archived_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """GET /entries/{id}/edits/{number} returns 404 without auth."""
        (client, _, _), entry = archived_entry

        resp = await client.get(f"/v1/entries/{entry['id']}/edits/1")
        assert resp.status_code == 404

    async def test_owner_can_list_edits(
        self,
        archived_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Owner CAN list edit proposals on their own archived entry."""
        (client, _, owner_token), entry = archived_entry

        resp = await client.get(
            f"/v1/entries/{entry['id']}/edits",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

    async def test_owner_can_get_edit_detail(
        self,
        archived_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Owner CAN get edit proposal detail on their own archived entry."""
        (client, _, owner_token), entry = archived_entry

        resp = await client.get(
            f"/v1/entries/{entry['id']}/edits/1",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200


class TestSubResourceIssuesArchived:
    """Scenario: Non-owners cannot access issues of archived entries."""

    async def test_list_issues_returns_404_for_non_owner(
        self,
        archived_entry: tuple[AuthedFixture, dict],
        other_user: AuthedFixture,
    ) -> None:
        """GET /entries/{id}/issues returns 404 for non-owners on archived entries."""
        (_, _, _), entry = archived_entry
        client, _, other_token = other_user

        resp = await client.get(
            f"/v1/entries/{entry['id']}/issues",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 404

    async def test_list_issues_returns_404_for_unauthenticated(
        self,
        archived_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """GET /entries/{id}/issues returns 404 without auth on archived entries."""
        (client, _, _), entry = archived_entry

        resp = await client.get(f"/v1/entries/{entry['id']}/issues")
        assert resp.status_code == 404

    async def test_get_issue_detail_returns_404_for_non_owner(
        self,
        archived_entry: tuple[AuthedFixture, dict],
        other_user: AuthedFixture,
    ) -> None:
        """GET /entries/{id}/issues/{number} returns 404 for non-owners."""
        (_, _, _), entry = archived_entry
        client, _, other_token = other_user

        resp = await client.get(
            f"/v1/entries/{entry['id']}/issues/1",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 404

    async def test_get_issue_detail_returns_404_for_unauthenticated(
        self,
        archived_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """GET /entries/{id}/issues/{number} returns 404 without auth."""
        (client, _, _), entry = archived_entry

        resp = await client.get(f"/v1/entries/{entry['id']}/issues/1")
        assert resp.status_code == 404

    async def test_owner_can_list_issues(
        self,
        archived_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Owner CAN list issues on their own archived entry."""
        (client, _, owner_token), entry = archived_entry

        resp = await client.get(
            f"/v1/entries/{entry['id']}/issues",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

    async def test_owner_can_get_issue_detail(
        self,
        archived_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Owner CAN get issue detail on their own archived entry."""
        (client, _, owner_token), entry = archived_entry

        resp = await client.get(
            f"/v1/entries/{entry['id']}/issues/1",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200


# ===========================================================================
# 3. Entity resolve — archived entries hidden from non-owners
# ===========================================================================


class TestEntityResolveArchived:
    """Scenario: Resolving an archived entry returns 404 for non-owners."""

    async def test_resolve_archived_entry_returns_404_for_non_owner(
        self,
        archived_entry: tuple[AuthedFixture, dict],
        other_user: AuthedFixture,
    ) -> None:
        """GET /entities/{id} returns 404 for non-owners when entry is archived."""
        (_, _, _), entry = archived_entry
        client, _, other_token = other_user

        resp = await client.get(
            f"/v1/entities/{entry['id']}",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 404

    async def test_resolve_archived_entry_returns_404_for_unauthenticated(
        self,
        archived_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """GET /entities/{id} returns 404 without auth when entry is archived."""
        (client, _, _), entry = archived_entry

        resp = await client.get(f"/v1/entities/{entry['id']}")
        assert resp.status_code == 404

    async def test_owner_can_resolve_archived_entry(
        self,
        archived_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Owner CAN resolve their own archived entry via /entities/{id}."""
        (client, _, owner_token), entry = archived_entry

        resp = await client.get(
            f"/v1/entities/{entry['id']}",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["entity_type"] == "entry"
        # Verify it actually returns the right entry with correct title
        assert data["title"] == "Archived Visibility Test Entry"


# ===========================================================================
# 4. References on archived entries
# ===========================================================================


class TestReferencesArchivedVisibility:
    """Scenario: Listing references on an archived entry returns 404 for
    non-owners. References TO an archived entry still appear in the source
    entry's detail response, but following the link yields 404.
    """

    async def test_list_references_returns_404_for_non_owner(
        self,
        archived_entry: tuple[AuthedFixture, dict],
        other_user: AuthedFixture,
    ) -> None:
        """GET /extensions/references/?entry_id={archived_id} returns 404
        for non-owners when the queried entry is archived."""
        (_, _, _), entry = archived_entry
        client, _, other_token = other_user

        resp = await client.get(
            "/v1/extensions/references/",
            params={"entry_id": entry["id"]},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 404

    async def test_list_references_returns_404_for_unauthenticated(
        self,
        archived_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """GET /extensions/references/?entry_id={archived_id} returns 404 without auth."""
        (client, _, _), entry = archived_entry

        resp = await client.get(
            "/v1/extensions/references/",
            params={"entry_id": entry["id"]},
        )
        assert resp.status_code == 404

    async def test_owner_can_list_references_on_archived(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Owner CAN list references on their own archived entry."""
        client, _, owner_token = owner

        entry_a = await create_entry(client, owner_token, title="Ref Owner A")
        entry_b = await create_entry(client, owner_token, title="Ref Owner B")
        for e in (entry_a, entry_b):
            await set_entry_repo_status(e2e_session_factory, e["id"], "ready")

        # Create reference A -> B
        resp = await client.post(
            f"/v1/extensions/references/{entry_a['id']}",
            json={"target_entry_id": entry_b["id"], "rel": "cites"},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 201

        # Archive A
        await set_entry_status(e2e_session_factory, entry_a["id"], "archived")

        # Owner can still list references on archived A
        resp = await client.get(
            "/v1/extensions/references/",
            params={"entry_id": entry_a["id"]},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

    async def test_reference_to_archived_still_in_source_detail(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """A reference TO an archived entry still appears in the source entry's
        detail response. The reference record persists regardless of the target's
        status.

        Setup: entry_source -> entry_target (reference). Archive entry_target.
        GET entry_source detail should still show the reference.
        """
        client, _, owner_token = owner

        entry_source = await create_entry(client, owner_token, title="Ref Source")
        entry_target = await create_entry(client, owner_token, title="Ref Target")
        for e in (entry_source, entry_target):
            await set_entry_repo_status(e2e_session_factory, e["id"], "ready")

        # Create reference: source -> target
        resp = await client.post(
            f"/v1/extensions/references/{entry_source['id']}",
            json={"target_entry_id": entry_target["id"], "rel": "supports"},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 201

        # Archive the target
        await set_entry_status(e2e_session_factory, entry_target["id"], "archived")

        # Non-owner views source entry detail — reference should still be there
        _, _, other_token = other_user
        resp = await client.get(
            f"/v1/entries/{entry_source['id']}",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        # The references field in the detail response should still list the ref
        assert len(data["references"]) == 1
        ref = data["references"][0]
        assert ref["to_entity_id"] == entry_target["id"]
        assert ref["rel"] == "supports"

    async def test_following_reference_to_archived_returns_404(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Following a reference to an archived entry returns 404 for non-owners.

        The reference record persists, but actually GETting the archived entry
        by ID returns 404 for non-owners.
        """
        client, _, owner_token = owner

        entry_source = await create_entry(client, owner_token, title="Follow Ref Source")
        entry_target = await create_entry(client, owner_token, title="Follow Ref Target")
        for e in (entry_source, entry_target):
            await set_entry_repo_status(e2e_session_factory, e["id"], "ready")

        # Create reference: source -> target
        resp = await client.post(
            f"/v1/extensions/references/{entry_source['id']}",
            json={"target_entry_id": entry_target["id"], "rel": "derives_from"},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 201

        # Archive the target
        await set_entry_status(e2e_session_factory, entry_target["id"], "archived")

        # Non-owner tries to follow the reference (GET the target entry)
        _, _, other_token = other_user
        resp = await client.get(
            f"/v1/entries/{entry_target['id']}",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 404

        # Unauthenticated also gets 404
        resp = await client.get(f"/v1/entries/{entry_target['id']}")
        assert resp.status_code == 404

        # But owner can still access it
        resp = await client.get(
            f"/v1/entries/{entry_target['id']}",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Follow Ref Target"
        assert resp.json()["status"] == "archived"
