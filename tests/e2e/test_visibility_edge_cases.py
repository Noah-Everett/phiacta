# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E edge-case tests for the visibility system.

Covers scenarios NOT tested in the core visibility, search visibility,
or graph visibility suites:
- Visibility transitions (public->private, private->public)
- Write operations blocked for non-owners on private entries
- Validation of invalid visibility values on PATCH
- Listing with explicit visibility query parameter
- Entity resolve edge cases (403 vs 404 distinction)
- References involving private entries
"""

from __future__ import annotations

import base64
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import phiacta.extensions.metadata.models  # noqa: F401
import phiacta.extensions.references.models  # noqa: F401
import phiacta.extensions.tags.models  # noqa: F401
import phiacta.extensions.types.models  # noqa: F401

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
    auth = await register_user(client, handle=f"edge-owner-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def other_user(client: httpx.AsyncClient) -> AuthedFixture:
    """Register a non-owner user and return (client, user_data, token)."""
    auth = await register_user(client, handle=f"edge-other-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


async def _ready_entry(
    client: httpx.AsyncClient,
    token: str,
    session_factory: async_sessionmaker[AsyncSession],
    fake_git: FakeGitService,
    *,
    title: str = "Edge Case Entry",
    summary: str = "edge case test entry",
) -> dict:
    """Create an entry, set it to ready, and populate minimal fake git data."""
    entry = await create_entry(client, token, title=title, summary=summary)
    entry_id = entry["id"]
    await set_entry_repo_status(session_factory, entry_id, "ready")

    eid = UUID(entry_id)
    fake_git.files[(eid, ".phiacta/content.md")] = b"# Content\nTest content."
    fake_git.files[(eid, ".phiacta/entry.yaml")] = b"id: test\nformat: markdown"
    fake_git.files[(eid, "README.md")] = b"# README"
    return entry


# ===========================================================================
# 1. Visibility transitions
# ===========================================================================


class TestVisibilityTransitions:
    """Scenario: Changing visibility after access has been observed."""

    async def test_public_to_private_blocks_previous_accessor(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """Entry starts public, non-owner accesses it, then it goes private -- 403."""
        client, _, owner_token = owner
        _, _, other_token = other_user

        entry = await _ready_entry(
            client, owner_token, e2e_session_factory, fake_git,
            title="Public Then Private",
        )

        # Non-owner can access while public
        resp = await client.get(
            f"/v1/entries/{entry['id']}",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 200

        # Owner patches to private
        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"visibility": "private"},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200
        assert resp.json()["visibility"] == "private"

        # Non-owner who previously had access now gets 403
        resp = await client.get(
            f"/v1/entries/{entry['id']}",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 403

    async def test_private_to_public_grants_previous_blocked_accessor(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """Entry starts private, non-owner gets 403, then it goes public -- 200."""
        client, _, owner_token = owner
        _, _, other_token = other_user

        entry = await _ready_entry(
            client, owner_token, e2e_session_factory, fake_git,
            title="Private Then Public",
        )
        await set_entry_visibility(e2e_session_factory, entry["id"], "private")

        # Non-owner gets 403 while private
        resp = await client.get(
            f"/v1/entries/{entry['id']}",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 403

        # Owner patches to public
        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"visibility": "public"},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

        # Non-owner who previously got 403 now gets 200
        resp = await client.get(
            f"/v1/entries/{entry['id']}",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 200

    async def test_patch_visibility_on_provisioning_entry(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PATCH visibility on a provisioning entry (repo_status != ready).

        Visibility is a core field. The PATCH endpoint requires repo_status=ready
        via get_writable_entry, so this should return 409 (not ready). This test
        documents the current behavior.
        """
        client, _, token = owner
        entry = await create_entry(client, token, title="Provisioning Entry")
        # repo_status defaults to "provisioning" -- do NOT set to ready

        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"visibility": "private"},
            headers=auth_header(token),
        )
        # get_writable_entry checks repo_status == "ready" and returns 409 if not
        assert resp.status_code == 409


# ===========================================================================
# 2. Write operations on private entries
# ===========================================================================


class TestWriteOperationsOnPrivateEntries:
    """Scenario: Non-owner write operations on private entries return 403."""

    async def test_non_owner_cannot_patch_metadata_on_private_entry(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """Non-owner PATCH metadata on a private entry returns 403."""
        client, _, owner_token = owner
        _, _, other_token = other_user

        entry = await _ready_entry(
            client, owner_token, e2e_session_factory, fake_git,
            title="Private No Patch",
        )
        await set_entry_visibility(e2e_session_factory, entry["id"], "private")

        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"title": "Hacked Title"},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 403

    async def test_non_owner_cannot_put_files_on_private_entry(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """Non-owner PUT files on a private entry returns 403."""
        client, _, owner_token = owner
        _, _, other_token = other_user

        entry = await _ready_entry(
            client, owner_token, e2e_session_factory, fake_git,
            title="Private No File Write",
        )
        await set_entry_visibility(e2e_session_factory, entry["id"], "private")

        resp = await client.put(
            f"/v1/entries/{entry['id']}/files/new-file.md",
            files={"content": ("file", b"unauthorized content", "application/octet-stream")},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 403

    async def test_non_owner_cannot_delete_files_on_private_entry(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """Non-owner DELETE files on a private entry returns 403."""
        client, _, owner_token = owner
        _, _, other_token = other_user

        entry = await _ready_entry(
            client, owner_token, e2e_session_factory, fake_git,
            title="Private No File Delete",
        )
        await set_entry_visibility(e2e_session_factory, entry["id"], "private")

        resp = await client.delete(
            f"/v1/entries/{entry['id']}/files/README.md",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 403

    async def test_non_owner_cannot_create_edit_proposal_on_private_entry(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """Non-owner creating an edit proposal on a private entry returns 403."""
        client, _, owner_token = owner
        _, _, other_token = other_user

        entry = await _ready_entry(
            client, owner_token, e2e_session_factory, fake_git,
            title="Private No Edit Proposal",
        )
        await set_entry_visibility(e2e_session_factory, entry["id"], "private")

        file_content = base64.b64encode(b"proposed change").decode()
        resp = await client.post(
            f"/v1/entries/{entry['id']}/edits",
            json={
                "title": "Unauthorized proposal",
                "body": "Should be rejected",
                "files": [{"path": "README.md", "content": file_content}],
            },
            headers=auth_header(other_token),
        )
        assert resp.status_code == 403

    async def test_non_owner_cannot_create_issue_on_private_entry(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """Non-owner creating an issue on a private entry returns 403."""
        client, _, owner_token = owner
        _, _, other_token = other_user

        entry = await _ready_entry(
            client, owner_token, e2e_session_factory, fake_git,
            title="Private No Issue",
        )
        await set_entry_visibility(e2e_session_factory, entry["id"], "private")

        resp = await client.post(
            f"/v1/entries/{entry['id']}/issues",
            json={"title": "Unauthorized issue", "body": "Should be rejected"},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 403

    async def test_owner_can_do_all_writes_on_own_private_entry(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """Owner CAN do all write operations on their own private entry."""
        client, _, owner_token = owner

        entry = await _ready_entry(
            client, owner_token, e2e_session_factory, fake_git,
            title="Private Owner Writes",
        )
        await set_entry_visibility(e2e_session_factory, entry["id"], "private")

        # PATCH metadata
        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"title": "Updated By Owner"},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated By Owner"

        # PUT file
        resp = await client.put(
            f"/v1/entries/{entry['id']}/files/owner-file.md",
            files={"content": ("file", b"owner content", "application/octet-stream")},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

        # DELETE file
        resp = await client.delete(
            f"/v1/entries/{entry['id']}/files/README.md",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

        # Create edit proposal
        file_content = base64.b64encode(b"owner proposal").decode()
        resp = await client.post(
            f"/v1/entries/{entry['id']}/edits",
            json={
                "title": "Owner proposal",
                "body": "Owner proposing changes",
                "files": [{"path": "proposal.md", "content": file_content}],
            },
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 201

        # Create issue
        resp = await client.post(
            f"/v1/entries/{entry['id']}/issues",
            json={"title": "Owner issue", "body": "Owner reporting"},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 201


# ===========================================================================
# 3. Validation
# ===========================================================================


class TestVisibilityValidation:
    """Scenario: Invalid and unauthorized visibility changes."""

    async def test_patch_with_invalid_visibility_returns_422(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """PATCH with invalid visibility value returns 422."""
        client, _, token = owner
        entry = await _ready_entry(
            client, token, e2e_session_factory, fake_git,
            title="Invalid Vis Patch",
        )

        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"visibility": "secret"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    async def test_patch_visibility_by_non_owner_returns_403(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """Non-owner PATCH visibility with valid value returns 403."""
        client, _, owner_token = owner
        _, _, other_token = other_user

        entry = await _ready_entry(
            client, owner_token, e2e_session_factory, fake_git,
            title="No Vis Patch For Non-Owner",
        )

        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"visibility": "private"},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 403

    async def test_create_entry_without_visibility_defaults_to_public(
        self,
        owner: AuthedFixture,
    ) -> None:
        """Create entry with no visibility field defaults to public."""
        client, _, token = owner

        resp = await client.post(
            "/v1/entries",
            json={"title": "No Visibility Field", "content_format": "markdown"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        assert resp.json()["visibility"] == "public"


# ===========================================================================
# 4. Listing with explicit visibility query parameter
# ===========================================================================


class TestListingVisibilityFilter:
    """Scenario: Using the visibility query parameter on GET /entries."""

    async def _setup_mixed_entries(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> tuple[dict, dict]:
        """Create one public and one private entry, both ready."""
        client, _, owner_token = owner
        public = await _ready_entry(
            client, owner_token, e2e_session_factory, fake_git,
            title="Filter Public Entry",
        )
        private = await _ready_entry(
            client, owner_token, e2e_session_factory, fake_git,
            title="Filter Private Entry",
        )
        await set_entry_visibility(e2e_session_factory, private["id"], "private")
        return public, private

    async def test_listing_visibility_private_shows_only_owners_private(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """GET /entries?visibility=private as owner shows only private entries."""
        client, _, owner_token = owner
        public, private = await self._setup_mixed_entries(
            owner, e2e_session_factory, fake_git,
        )

        resp = await client.get(
            "/v1/entries",
            params={"visibility": "private"},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200
        ids = {item["id"] for item in resp.json()["items"]}
        assert private["id"] in ids
        assert public["id"] not in ids

    async def test_listing_visibility_private_as_non_owner_shows_nothing(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """GET /entries?visibility=private as non-owner returns empty list."""
        client, _, owner_token = owner
        _, _, other_token = other_user
        public, private = await self._setup_mixed_entries(
            owner, e2e_session_factory, fake_git,
        )

        resp = await client.get(
            "/v1/entries",
            params={"visibility": "private"},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 200
        ids = {item["id"] for item in resp.json()["items"]}
        # Non-owner sees no private entries (not even their own -- they have none)
        assert private["id"] not in ids
        assert public["id"] not in ids

    async def test_listing_visibility_all_as_owner_shows_both(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """GET /entries?visibility=all as owner shows public and private."""
        client, _, owner_token = owner
        public, private = await self._setup_mixed_entries(
            owner, e2e_session_factory, fake_git,
        )

        resp = await client.get(
            "/v1/entries",
            params={"visibility": "all"},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200
        ids = {item["id"] for item in resp.json()["items"]}
        assert public["id"] in ids
        assert private["id"] in ids

    async def test_listing_visibility_all_as_non_owner_shows_only_public(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """GET /entries?visibility=all as non-owner shows only public entries."""
        client, _, owner_token = owner
        _, _, other_token = other_user
        public, private = await self._setup_mixed_entries(
            owner, e2e_session_factory, fake_git,
        )

        resp = await client.get(
            "/v1/entries",
            params={"visibility": "all"},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 200
        ids = {item["id"] for item in resp.json()["items"]}
        assert public["id"] in ids
        assert private["id"] not in ids

    async def test_listing_visibility_invalid_returns_422(
        self,
        owner: AuthedFixture,
    ) -> None:
        """GET /entries?visibility=invalid returns 422."""
        client, _, token = owner

        resp = await client.get(
            "/v1/entries",
            params={"visibility": "invalid"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422


# ===========================================================================
# 5. Entity resolve edge cases
# ===========================================================================


class TestEntityResolveEdgeCases:
    """Scenario: Entity resolve distinguishes 403 (private) from 404 (missing)."""

    async def test_entity_resolve_private_returns_403_not_404_for_non_owner(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """Entity resolve for a private entry returns 403, not 404, for non-owner.

        This verifies the system does not mask the existence of private entries
        with 404 -- it explicitly returns 403 to indicate access is denied.
        """
        client, _, owner_token = owner
        _, _, other_token = other_user

        entry = await _ready_entry(
            client, owner_token, e2e_session_factory, fake_git,
            title="Private Entity Resolve",
        )
        await set_entry_visibility(e2e_session_factory, entry["id"], "private")

        resp = await client.get(
            f"/v1/entities/{entry['id']}",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 403

    async def test_entity_resolve_nonexistent_uuid_returns_404(
        self,
        owner: AuthedFixture,
    ) -> None:
        """Entity resolve for a completely nonexistent UUID returns 404."""
        client, _, token = owner

        fake_uuid = str(uuid4())
        resp = await client.get(
            f"/v1/entities/{fake_uuid}",
            headers=auth_header(token),
        )
        assert resp.status_code == 404


# ===========================================================================
# 6. References involving private entries
# ===========================================================================


class TestReferencesAndPrivateEntries:
    """Scenario: References to/from private entries in graph traversal."""

    async def test_reference_to_private_target_hidden_in_graph_traversal(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """Public entry references a private entry -- graph hides the target
        from non-owners but the reference record persists for the owner.
        """
        client, _, owner_token = owner
        _, _, other_token = other_user

        public_entry = await _ready_entry(
            client, owner_token, e2e_session_factory, fake_git,
            title="Ref Source Public",
        )
        private_target = await _ready_entry(
            client, owner_token, e2e_session_factory, fake_git,
            title="Ref Target Private",
        )
        await set_entry_visibility(
            e2e_session_factory, private_target["id"], "private",
        )

        # Owner creates reference from public to private
        resp = await client.post(
            f"/v1/extensions/references/{public_entry['id']}",
            json={
                "target_entry_id": private_target["id"],
                "rel": "cites",
            },
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 201

        # Non-owner traverses graph from public entry -- private target hidden
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": public_entry["id"], "depth": 1},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        node_ids = {n["id"] for n in data["nodes"]}
        assert public_entry["id"] in node_ids
        assert private_target["id"] not in node_ids
        # No edges to the private target
        for edge in data["edges"]:
            assert edge["target"] != private_target["id"]

        # Owner traverses same graph -- sees both
        resp = await client.get(
            "/v1/tools/graph/",
            params={"entry_ids": public_entry["id"], "depth": 1},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        node_ids = {n["id"] for n in data["nodes"]}
        assert public_entry["id"] in node_ids
        assert private_target["id"] in node_ids

    async def test_creating_reference_to_private_entry_by_uuid(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """A user can reference a private entry by UUID from their own entry.

        References are like academic citations — you can cite something by
        its identifier without needing access to the full content. The
        reference lives on the caller's entry, not the target.
        """
        client, _, owner_token = owner
        _, _, other_token = other_user

        # Owner creates a private entry
        private_entry = await _ready_entry(
            client, owner_token, e2e_session_factory, fake_git,
            title="Private Target By Owner",
        )
        await set_entry_visibility(
            e2e_session_factory, private_entry["id"], "private",
        )

        # Other user creates their own public entry
        other_entry = await _ready_entry(
            client, other_token, e2e_session_factory, fake_git,
            title="Other User Source Entry",
        )

        # Other user creates a reference from their entry to the private entry
        resp = await client.post(
            f"/v1/extensions/references/{other_entry['id']}",
            json={
                "target_entry_id": private_entry["id"],
                "rel": "cites",
            },
            headers=auth_header(other_token),
        )
        assert resp.status_code == 201

