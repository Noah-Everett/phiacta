# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for entry archival and unarchival (NEV-128).

POST /v1/entries/{id}/archive — soft-archive an entry (DB + Forgejo).
POST /v1/entries/{id}/unarchive — restore an archived entry.
"""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from tests.e2e.conftest import (
    FakeGitService,
    auth_header,
    create_entry,
    register_user,
    set_entry_repo_status,
    set_entry_status,
)

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    """Register a user and return (client, user_data, token)."""
    auth = await register_user(client, handle="archive-test")
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def ready_entry(
    authed: AuthedFixture,
    e2e_session_factory,  # type: ignore[type-arg]
) -> tuple[AuthedFixture, dict]:
    """Create an entry and set it to ready status."""
    client, _, token = authed
    entry = await create_entry(client, token, title="Archival Test Entry")
    await set_entry_repo_status(e2e_session_factory, entry["id"], "ready")
    return authed, entry


class TestArchiveEntry:
    """Tests for POST /v1/entries/{id}/archive."""

    async def test_archive_active_entry(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        fake_git: FakeGitService,
    ) -> None:
        (client, _, token), entry = ready_entry

        resp = await client.post(
            f"/v1/entries/{entry['id']}/archive",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "archived"

        # Verify archive_repo was called on FakeGitService
        assert entry["id"] in [str(eid) for eid in fake_git.archived_repos]

    async def test_archive_draft_entry(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        e2e_session_factory,  # type: ignore[type-arg]
        fake_git: FakeGitService,
    ) -> None:
        (client, _, token), entry = ready_entry
        await set_entry_status(e2e_session_factory, entry["id"], "draft")

        resp = await client.post(
            f"/v1/entries/{entry['id']}/archive",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "archived"

    async def test_archive_already_archived_returns_409(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        e2e_session_factory,  # type: ignore[type-arg]
    ) -> None:
        (client, _, token), entry = ready_entry
        await set_entry_status(e2e_session_factory, entry["id"], "archived")

        resp = await client.post(
            f"/v1/entries/{entry['id']}/archive",
            headers=auth_header(token),
        )
        assert resp.status_code == 409

    async def test_archive_retracted_entry_returns_409(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        e2e_session_factory,  # type: ignore[type-arg]
    ) -> None:
        (client, _, token), entry = ready_entry
        await set_entry_status(e2e_session_factory, entry["id"], "retracted")

        resp = await client.post(
            f"/v1/entries/{entry['id']}/archive",
            headers=auth_header(token),
        )
        assert resp.status_code == 409

    async def test_archive_wrong_author_returns_403(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, _), entry = ready_entry
        other = await register_user(client, handle="other-archive")

        resp = await client.post(
            f"/v1/entries/{entry['id']}/archive",
            headers=auth_header(other["access_token"]),
        )
        assert resp.status_code == 403

    async def test_archive_unauthenticated_returns_401(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, _), entry = ready_entry

        resp = await client.post(f"/v1/entries/{entry['id']}/archive")
        assert resp.status_code == 401

    async def test_archive_nonexistent_entry_returns_404(
        self, authed: AuthedFixture,
    ) -> None:
        client, _, token = authed
        resp = await client.post(
            f"/v1/entries/{uuid4()}/archive",
            headers=auth_header(token),
        )
        assert resp.status_code == 404

    async def test_archive_provisioning_entry_returns_409(
        self, authed: AuthedFixture,
    ) -> None:
        client, _, token = authed
        entry = await create_entry(client, token)
        # Entry is still provisioning — not ready

        resp = await client.post(
            f"/v1/entries/{entry['id']}/archive",
            headers=auth_header(token),
        )
        assert resp.status_code == 409

    async def test_archived_entry_still_readable(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        fake_git: FakeGitService,
    ) -> None:
        """GET /entries/{id} should still return archived entries."""
        (client, _, token), entry = ready_entry

        # Archive it
        resp = await client.post(
            f"/v1/entries/{entry['id']}/archive",
            headers=auth_header(token),
        )
        assert resp.status_code == 200

        # Should still be readable by ID
        resp = await client.get(f"/v1/entries/{entry['id']}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "archived"

    async def test_archived_entry_excluded_from_default_list(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        fake_git: FakeGitService,
    ) -> None:
        """GET /entries with default status=active should exclude archived entries."""
        (client, _, token), entry = ready_entry

        # Archive it
        await client.post(
            f"/v1/entries/{entry['id']}/archive",
            headers=auth_header(token),
        )

        # Default list (status=active) should not include it
        resp = await client.get("/v1/entries")
        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()["items"]]
        assert entry["id"] not in ids

    async def test_archived_entry_included_in_all_list(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        fake_git: FakeGitService,
    ) -> None:
        """GET /entries?status=all should include archived entries."""
        (client, _, token), entry = ready_entry

        await client.post(
            f"/v1/entries/{entry['id']}/archive",
            headers=auth_header(token),
        )

        resp = await client.get("/v1/entries", params={"status": "all"})
        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()["items"]]
        assert entry["id"] in ids

    async def test_archived_entry_file_write_returns_403(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        fake_git: FakeGitService,
    ) -> None:
        """File writes to archived entries should be rejected."""
        (client, _, token), entry = ready_entry

        await client.post(
            f"/v1/entries/{entry['id']}/archive",
            headers=auth_header(token),
        )

        resp = await client.put(
            f"/v1/entries/{entry['id']}/files/README.md",
            files={"content": ("file", b"hello", "application/octet-stream")},
            headers=auth_header(token),
        )
        assert resp.status_code == 403

    async def test_archived_entry_update_returns_403(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        fake_git: FakeGitService,
    ) -> None:
        """Metadata updates to archived entries should be rejected."""
        (client, _, token), entry = ready_entry

        await client.post(
            f"/v1/entries/{entry['id']}/archive",
            headers=auth_header(token),
        )

        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"title": "Should Fail"},
            headers=auth_header(token),
        )
        assert resp.status_code == 403


class TestUnarchiveEntry:
    """Tests for POST /v1/entries/{id}/unarchive."""

    async def test_unarchive_entry(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        e2e_session_factory,  # type: ignore[type-arg]
        fake_git: FakeGitService,
    ) -> None:
        (client, _, token), entry = ready_entry

        # Archive first
        await client.post(
            f"/v1/entries/{entry['id']}/archive",
            headers=auth_header(token),
        )

        # Unarchive
        resp = await client.post(
            f"/v1/entries/{entry['id']}/unarchive",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"

    async def test_unarchive_non_archived_returns_409(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, token), entry = ready_entry
        # Entry is active, not archived
        resp = await client.post(
            f"/v1/entries/{entry['id']}/unarchive",
            headers=auth_header(token),
        )
        assert resp.status_code == 409

    async def test_unarchive_wrong_author_returns_403(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        e2e_session_factory,  # type: ignore[type-arg]
        fake_git: FakeGitService,
    ) -> None:
        (client, _, token), entry = ready_entry

        # Archive first
        await client.post(
            f"/v1/entries/{entry['id']}/archive",
            headers=auth_header(token),
        )

        # Different user tries to unarchive
        other = await register_user(client, handle="other-unarch")
        resp = await client.post(
            f"/v1/entries/{entry['id']}/unarchive",
            headers=auth_header(other["access_token"]),
        )
        assert resp.status_code == 403

    async def test_unarchive_unauthenticated_returns_401(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        e2e_session_factory,  # type: ignore[type-arg]
    ) -> None:
        (client, _, _), entry = ready_entry
        await set_entry_status(e2e_session_factory, entry["id"], "archived")

        resp = await client.post(f"/v1/entries/{entry['id']}/unarchive")
        assert resp.status_code == 401

    async def test_unarchive_then_update_works(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        fake_git: FakeGitService,
    ) -> None:
        """Full lifecycle: create -> archive -> unarchive -> update title."""
        (client, user, token), entry = ready_entry
        entry_id = entry["id"]

        resp = await client.post(f"/v1/entries/{entry_id}/archive", headers=auth_header(token))
        assert resp.status_code == 200

        resp = await client.post(f"/v1/entries/{entry_id}/unarchive", headers=auth_header(token))
        assert resp.status_code == 200

        resp = await client.patch(
            f"/v1/entries/{entry_id}",
            json={"title": "After Unarchive"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "After Unarchive"
