# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for the visibility model (replaces status-based access control).

Tests the full HTTP path for visibility enforcement:
- Private entries return 403 for non-owners on direct access
- Private entries return 403 for unauthenticated on direct access
- Owner can always access their private entries
- Private entries silently excluded from listings
- Create entry with visibility=private
- Default visibility is public
- PATCH visibility changes
- Private entry sub-resources return 403 for non-owner
- Owner can always access sub-resources of their private entry
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, text
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
)

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def set_entry_visibility(
    session_factory: async_sessionmaker[AsyncSession],
    entry_id: str,
    visibility: str,
) -> None:
    """Set an entry's visibility directly in the DB."""
    from phiacta.core.models.entry import Entry

    async with session_factory() as session:
        result = await session.execute(
            select(Entry).where(Entry.id == UUID(entry_id))
        )
        entry = result.scalar_one()
        entry.visibility = visibility
        await session.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mount_routers(client: httpx.AsyncClient) -> None:
    from phiacta.extensions.metadata import router as mr
    from phiacta.extensions.references import router as rr
    from phiacta.extensions.tags import router as tagr
    from phiacta.extensions.types import router as tr
    from phiacta.main import app as _app

    _app.include_router(mr, prefix="/v1/extensions/metadata", tags=["metadata"])
    _app.include_router(tr, prefix="/v1/extensions/types", tags=["types"])
    _app.include_router(rr, prefix="/v1/extensions/references", tags=["references"])
    _app.include_router(tagr, prefix="/v1/extensions/tags", tags=["tags"])
    yield  # type: ignore[misc]
    prefixes = (
        "/v1/extensions/metadata", "/v1/extensions/types",
        "/v1/extensions/references", "/v1/extensions/tags",
    )
    _app.routes[:] = [
        r for r in _app.routes
        if not (hasattr(r, "path") and any(r.path.startswith(p) for p in prefixes))
    ]


@pytest.fixture
async def owner(client: httpx.AsyncClient) -> AuthedFixture:
    """Register the entry owner and return (client, user_data, token)."""
    auth = await register_user(client, username=f"vis-owner-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def other_user(client: httpx.AsyncClient) -> AuthedFixture:
    """Register a non-owner user and return (client, user_data, token)."""
    auth = await register_user(client, username=f"vis-other-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def private_entry(
    owner: AuthedFixture,
    e2e_session_factory: async_sessionmaker[AsyncSession],
    fake_git: FakeGitService,
) -> tuple[AuthedFixture, dict]:
    """Create an entry, set it to ready, then make it private.

    Also populates the FakeGitService with minimal file data so sub-resource
    endpoints have something to return for the owner.
    """
    client, _, token = owner
    entry = await create_entry(
        client, token, title="Private Visibility Test Entry",
        summary="An entry that will be made private for visibility testing",
    )
    entry_id = entry["id"]
    await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

    # Populate fake git with file data so the owner CAN access sub-resources
    eid = UUID(entry_id)
    fake_git.files[(eid, ".phiacta/content.md")] = b"# Private Content\nSecret text."
    fake_git.files[(eid, ".phiacta/entry.yaml")] = b"id: test\nformat: markdown"

    # Populate commit history
    ts = datetime(2026, 3, 20, 12, 0, 0, tzinfo=UTC)
    fake_git.commit_history[eid] = [
        CommitInfo(
            sha="aabbcc1122334455667788990011223344556677",
            message="Initial commit",
            author=AuthorInfo(name="vis-owner", email="owner@phiacta.local"),
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

    # Set entry to private
    await set_entry_visibility(e2e_session_factory, entry_id, "private")

    return owner, entry


# ===========================================================================
# 1. Direct access — GET /entries/{id}
# ===========================================================================


class TestDirectAccess:
    """Scenario: Direct access to private entries via GET /entries/{id}."""

    async def test_private_entry_returns_403_for_non_owner(
        self,
        private_entry: tuple[AuthedFixture, dict],
        other_user: AuthedFixture,
    ) -> None:
        """GET /entries/{id} returns 403 for a non-owner on a private entry."""
        (_, _, _), entry = private_entry
        client, _, other_token = other_user

        resp = await client.get(
            f"/v1/entries/{entry['id']}",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 403

    async def test_private_entry_returns_403_for_unauthenticated(
        self,
        private_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """GET /entries/{id} returns 403 for unauthenticated on a private entry."""
        (client, _, _), entry = private_entry

        resp = await client.get(f"/v1/entries/{entry['id']}")
        assert resp.status_code == 403

    async def test_owner_can_get_private_entry(
        self,
        private_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Owner can GET their own private entry (200)."""
        (client, _, owner_token), entry = private_entry

        resp = await client.get(
            f"/v1/entries/{entry['id']}",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == entry["id"]
        assert data["title"] == "Private Visibility Test Entry"
        assert data["visibility"] == "private"

    async def test_public_entry_accessible_by_anyone(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Public entries remain accessible by everyone (baseline check)."""
        client, _, owner_token = owner
        entry = await create_entry(client, owner_token, title="Public Entry")
        await set_entry_repo_status(e2e_session_factory, entry["id"], "ready")

        # Non-owner can access
        _, _, other_token = other_user
        resp = await client.get(
            f"/v1/entries/{entry['id']}",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 200
        assert resp.json()["visibility"] == "public"

        # Unauthenticated can access
        resp = await client.get(f"/v1/entries/{entry['id']}")
        assert resp.status_code == 200


# ===========================================================================
# 2. Listings — GET /entries
# ===========================================================================


class TestListingVisibility:
    """Scenario: Private entries are silently excluded from listings."""

    async def test_private_entry_excluded_from_listing_for_non_owner(
        self,
        private_entry: tuple[AuthedFixture, dict],
        other_user: AuthedFixture,
    ) -> None:
        """Private entries are silently excluded from GET /entries for non-owners."""
        (_, _, _), entry = private_entry
        client, _, other_token = other_user

        resp = await client.get(
            "/v1/entries",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()["items"]]
        assert entry["id"] not in ids

    async def test_private_entry_excluded_from_listing_for_unauthenticated(
        self,
        private_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Private entries are silently excluded from GET /entries without auth."""
        (client, _, _), entry = private_entry

        resp = await client.get("/v1/entries")
        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()["items"]]
        assert entry["id"] not in ids

    async def test_owner_sees_own_private_entry_in_listing(
        self,
        private_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Owner sees their own private entries in GET /entries."""
        (client, _, owner_token), entry = private_entry

        resp = await client.get(
            "/v1/entries",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()["items"]]
        assert entry["id"] in ids

    async def test_mixed_visibility_listing(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Listing shows public entries to everyone and private only to owner."""
        client, _, owner_token = owner

        public_entry = await create_entry(client, owner_token, title="Public Listed")
        private_entry = await create_entry(client, owner_token, title="Private Listed")
        for e in (public_entry, private_entry):
            await set_entry_repo_status(e2e_session_factory, e["id"], "ready")
        await set_entry_visibility(e2e_session_factory, private_entry["id"], "private")

        # Owner sees both
        resp = await client.get("/v1/entries", headers=auth_header(owner_token))
        owner_ids = {item["id"] for item in resp.json()["items"]}
        assert public_entry["id"] in owner_ids
        assert private_entry["id"] in owner_ids

        # Non-owner sees only public
        _, _, other_token = other_user
        resp = await client.get("/v1/entries", headers=auth_header(other_token))
        other_ids = {item["id"] for item in resp.json()["items"]}
        assert public_entry["id"] in other_ids
        assert private_entry["id"] not in other_ids


# ===========================================================================
# 3. Create with visibility
# ===========================================================================


class TestCreateWithVisibility:
    """Scenario: Creating entries with explicit visibility."""

    async def test_create_entry_with_visibility_private(
        self,
        owner: AuthedFixture,
    ) -> None:
        """POST /entries with visibility=private creates a private entry."""
        client, _, token = owner

        resp = await client.post(
            "/v1/entries",
            json={
                "title": "Born Private",
                "content_format": "markdown",
                "visibility": "private",
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["visibility"] == "private"

        # Verify persisted: GET by owner
        resp = await client.get(
            f"/v1/entries/{data['id']}",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["visibility"] == "private"

    async def test_default_visibility_is_public(
        self,
        owner: AuthedFixture,
    ) -> None:
        """Creating an entry without specifying visibility defaults to public."""
        client, _, token = owner

        entry = await create_entry(client, token, title="Default Visibility Entry")
        assert entry["visibility"] == "public"

    async def test_create_entry_with_visibility_public(
        self,
        owner: AuthedFixture,
    ) -> None:
        """POST /entries with visibility=public creates a public entry (explicit)."""
        client, _, token = owner

        resp = await client.post(
            "/v1/entries",
            json={
                "title": "Explicitly Public",
                "content_format": "markdown",
                "visibility": "public",
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        assert resp.json()["visibility"] == "public"

    async def test_create_entry_with_invalid_visibility(
        self,
        owner: AuthedFixture,
    ) -> None:
        """POST /entries with an invalid visibility value returns 422."""
        client, _, token = owner

        resp = await client.post(
            "/v1/entries",
            json={
                "title": "Invalid Visibility",
                "content_format": "markdown",
                "visibility": "secret",
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 422


# ===========================================================================
# 4. PATCH visibility
# ===========================================================================


class TestPatchVisibility:
    """Scenario: Changing entry visibility via PATCH."""

    async def test_patch_public_to_private(
        self,
        owner: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PATCH /entries/{id} can change visibility from public to private."""
        client, _, token = owner
        entry = await create_entry(client, token, title="Will Go Private")
        await set_entry_repo_status(e2e_session_factory, entry["id"], "ready")

        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"visibility": "private"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["visibility"] == "private"

        # Verify persisted
        resp = await client.get(
            f"/v1/entries/{entry['id']}",
            headers=auth_header(token),
        )
        assert resp.json()["visibility"] == "private"

    async def test_patch_private_to_public(
        self,
        private_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """PATCH /entries/{id} can change visibility from private to public."""
        (client, _, owner_token), entry = private_entry

        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"visibility": "public"},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200
        assert resp.json()["visibility"] == "public"

        # After making public, unauthenticated should be able to access
        resp = await client.get(f"/v1/entries/{entry['id']}")
        assert resp.status_code == 200
        assert resp.json()["visibility"] == "public"

    async def test_patch_visibility_non_owner_rejected(
        self,
        owner: AuthedFixture,
        other_user: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Non-owner cannot PATCH the visibility of someone else's entry."""
        client, _, owner_token = owner
        entry = await create_entry(client, owner_token, title="No Patch For You")
        await set_entry_repo_status(e2e_session_factory, entry["id"], "ready")

        _, _, other_token = other_user
        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"visibility": "private"},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 403

    async def test_owner_can_always_edit_private_entry(
        self,
        private_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Owner can update metadata on their own private entry (no EDITABLE_STATUSES concept)."""
        (client, _, owner_token), entry = private_entry

        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"title": "Updated Private Title"},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated Private Title"


# ===========================================================================
# 5. Sub-resource access on private entries
# ===========================================================================


class TestSubResourceFiles:
    """Scenario: Non-owners cannot access files of private entries."""

    async def test_list_files_returns_403_for_non_owner(
        self,
        private_entry: tuple[AuthedFixture, dict],
        other_user: AuthedFixture,
    ) -> None:
        (_, _, _), entry = private_entry
        client, _, other_token = other_user
        resp = await client.get(
            f"/v1/entries/{entry['id']}/files",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 403

    async def test_list_files_returns_403_for_unauthenticated(
        self,
        private_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, _), entry = private_entry
        resp = await client.get(f"/v1/entries/{entry['id']}/files")
        assert resp.status_code == 403

    async def test_read_file_returns_403_for_non_owner(
        self,
        private_entry: tuple[AuthedFixture, dict],
        other_user: AuthedFixture,
    ) -> None:
        (_, _, _), entry = private_entry
        client, _, other_token = other_user
        resp = await client.get(
            f"/v1/entries/{entry['id']}/files/.phiacta/content.md",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 403

    async def test_owner_can_list_files(
        self,
        private_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, owner_token), entry = private_entry
        resp = await client.get(
            f"/v1/entries/{entry['id']}/files",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

    async def test_owner_can_read_file(
        self,
        private_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, owner_token), entry = private_entry
        resp = await client.get(
            f"/v1/entries/{entry['id']}/files/.phiacta/content.md",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200


class TestSubResourceHistory:
    """Scenario: Non-owners cannot access history of private entries."""

    async def test_list_history_returns_403_for_non_owner(
        self,
        private_entry: tuple[AuthedFixture, dict],
        other_user: AuthedFixture,
    ) -> None:
        (_, _, _), entry = private_entry
        client, _, other_token = other_user
        resp = await client.get(
            f"/v1/entries/{entry['id']}/history",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 403

    async def test_owner_can_list_history(
        self,
        private_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, owner_token), entry = private_entry
        resp = await client.get(
            f"/v1/entries/{entry['id']}/history",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200


class TestSubResourceEdits:
    """Scenario: Non-owners cannot access edit proposals of private entries."""

    async def test_list_edits_returns_403_for_non_owner(
        self,
        private_entry: tuple[AuthedFixture, dict],
        other_user: AuthedFixture,
    ) -> None:
        (_, _, _), entry = private_entry
        client, _, other_token = other_user
        resp = await client.get(
            f"/v1/entries/{entry['id']}/edits",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 403

    async def test_owner_can_list_edits(
        self,
        private_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, owner_token), entry = private_entry
        resp = await client.get(
            f"/v1/entries/{entry['id']}/edits",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200


class TestSubResourceIssues:
    """Scenario: Non-owners cannot access issues of private entries."""

    async def test_list_issues_returns_403_for_non_owner(
        self,
        private_entry: tuple[AuthedFixture, dict],
        other_user: AuthedFixture,
    ) -> None:
        (_, _, _), entry = private_entry
        client, _, other_token = other_user
        resp = await client.get(
            f"/v1/entries/{entry['id']}/issues",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 403

    async def test_owner_can_list_issues(
        self,
        private_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, owner_token), entry = private_entry
        resp = await client.get(
            f"/v1/entries/{entry['id']}/issues",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200


# ===========================================================================
# 6. Entity resolve — private entries return 403 for non-owners
# ===========================================================================


class TestEntityResolveVisibility:
    async def test_resolve_private_entry_returns_403_for_non_owner(
        self,
        private_entry: tuple[AuthedFixture, dict],
        other_user: AuthedFixture,
    ) -> None:
        (_, _, _), entry = private_entry
        client, _, other_token = other_user
        resp = await client.get(
            f"/v1/entities/{entry['id']}",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 403

    async def test_resolve_private_entry_returns_403_for_unauthenticated(
        self,
        private_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, _), entry = private_entry
        resp = await client.get(f"/v1/entities/{entry['id']}")
        assert resp.status_code == 403

    async def test_owner_can_resolve_private_entry(
        self,
        private_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, owner_token), entry = private_entry
        resp = await client.get(
            f"/v1/entities/{entry['id']}",
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["entity_type"] == "entry"


# ===========================================================================
# 7. File writes on private entries — owner can always write
# ===========================================================================


class TestFileWriteOnPrivateEntry:
    async def test_owner_can_write_file_to_private_entry(
        self,
        private_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, owner_token), entry = private_entry
        resp = await client.put(
            f"/v1/entries/{entry['id']}/files/README.md",
            files={"content": ("file", b"hello world", "application/octet-stream")},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200

    async def test_non_owner_cannot_write_file_to_private_entry(
        self,
        private_entry: tuple[AuthedFixture, dict],
        other_user: AuthedFixture,
    ) -> None:
        (_, _, _), entry = private_entry
        client, _, other_token = other_user
        resp = await client.put(
            f"/v1/entries/{entry['id']}/files/README.md",
            files={"content": ("file", b"hello world", "application/octet-stream")},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 403
