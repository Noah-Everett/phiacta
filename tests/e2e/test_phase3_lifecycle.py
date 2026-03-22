# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Phase 3 cross-cutting E2E tests (NEV-129).

These tests exercise multi-feature lifecycle scenarios that span entry
creation, file CRUD, metadata updates, history, and archival. Each test
verifies that operations compose correctly across module boundaries.
"""

from __future__ import annotations

import base64
from uuid import UUID

import httpx
import pytest
import yaml

from tests.e2e.conftest import (
    FakeGitService,
    auth_header,
    create_entry,
    register_user,
    set_entry_repo_status,
)


@pytest.fixture
async def user_a(client: httpx.AsyncClient) -> tuple[dict, str]:
    """Register user A and return (user_data, token)."""
    auth = await register_user(client, handle="user-a")
    return auth["user"], auth["access_token"]


@pytest.fixture
async def user_b(client: httpx.AsyncClient) -> tuple[dict, str]:
    """Register user B and return (user_data, token)."""
    auth = await register_user(client, handle="user-b")
    return auth["user"], auth["access_token"]


def _seed_entry_yaml(
    fake_git: FakeGitService,
    entry_id: str,
    user_id: str,
    user_handle: str,
    *,
    title: str = "Test Entry",
) -> None:
    """Populate entry.yaml in FakeGitService for the update endpoint."""
    yaml_bytes = yaml.dump(
        {
            "entry_id": f"ent_{entry_id}",
            "schema_version": 1,
            "title": title,
            "author": {"id": f"usr_{user_id}", "name": user_handle},
            "created_at": "2026-01-01T00:00:00",
            "content_format": "markdown",
        },
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    ).encode()
    fake_git.files[(UUID(entry_id), ".phiacta/entry.yaml")] = yaml_bytes


class TestFullEntryLifecycle:
    """Create → ready → write file → read → update metadata → archive →
    verify reads → unarchive → write again."""

    async def test_complete_lifecycle(
        self,
        client: httpx.AsyncClient,
        user_a: tuple[dict, str],
        e2e_session_factory,
        fake_git: FakeGitService,
    ) -> None:
        user, token = user_a
        headers = auth_header(token)

        # 1. Create entry
        entry = await create_entry(client, token, title="Lifecycle Entry")
        entry_id = entry["id"]
        assert entry["repo_status"] == "provisioning"
        assert entry["status"] == "active"

        # 2. Cannot write files while provisioning
        content_b64 = base64.b64encode(b"# Hello").decode()
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/README.md",
            json={"content": content_b64},
            headers=headers,
        )
        assert resp.status_code == 409

        # 3. Mark entry as ready (simulates outbox worker completing)
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # 4. Write a file
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/README.md",
            json={"content": content_b64, "message": "Add README"},
            headers=headers,
        )
        assert resp.status_code == 200
        write_sha = resp.json()["sha"]
        assert write_sha

        # 5. Read file back — verify content matches
        resp = await client.get(f"/v1/entries/{entry_id}/files/README.md")
        assert resp.status_code == 200
        assert resp.content == b"# Hello"

        # 6. List files — README.md should appear
        resp = await client.get(f"/v1/entries/{entry_id}/files")
        assert resp.status_code == 200
        file_names = [f["name"] for f in resp.json()]
        assert "README.md" in file_names

        # 7. Update metadata
        _seed_entry_yaml(
            fake_git, entry_id, user["id"], "user-a", title="Lifecycle Entry",
        )
        resp = await client.patch(
            f"/v1/entries/{entry_id}",
            json={"title": "Updated Lifecycle Entry"},
            headers=headers,
        )
        assert resp.status_code == 200
        # Verify YAML was updated in git
        yaml_data = yaml.safe_load(
            fake_git.files[(UUID(entry_id), ".phiacta/entry.yaml")]
        )
        assert yaml_data["title"] == "Updated Lifecycle Entry"

        # 8. Archive entry
        resp = await client.post(
            f"/v1/entries/{entry_id}/archive", headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "archived"
        assert UUID(entry_id) in fake_git.archived_repos

        # 9. Reads still work on archived entry
        resp = await client.get(f"/v1/entries/{entry_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "archived"

        resp = await client.get(f"/v1/entries/{entry_id}/files/README.md")
        assert resp.status_code == 200
        assert resp.content == b"# Hello"

        # 10. Writes blocked on archived entry
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/new.txt",
            json={"content": base64.b64encode(b"nope").decode()},
            headers=headers,
        )
        assert resp.status_code == 403

        resp = await client.patch(
            f"/v1/entries/{entry_id}",
            json={"title": "Should Fail"},
            headers=headers,
        )
        assert resp.status_code == 403

        # 11. Unarchive
        resp = await client.post(
            f"/v1/entries/{entry_id}/unarchive", headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"
        assert UUID(entry_id) not in fake_git.archived_repos

        # 12. Writes work again after unarchival
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/notes.txt",
            json={
                "content": base64.b64encode(b"Post-unarchive note").decode(),
                "message": "Add notes after unarchive",
            },
            headers=headers,
        )
        assert resp.status_code == 200

        resp = await client.get(f"/v1/entries/{entry_id}/files/notes.txt")
        assert resp.status_code == 200
        assert resp.content == b"Post-unarchive note"


class TestPhiactaProtectionLifecycle:
    """.phiacta/ directory is protected across all write operations."""

    async def test_phiacta_protected_for_all_write_operations(
        self,
        client: httpx.AsyncClient,
        user_a: tuple[dict, str],
        e2e_session_factory,
    ) -> None:
        _, token = user_a
        headers = auth_header(token)
        entry = await create_entry(client, token)
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        content_b64 = base64.b64encode(b"injected").decode()

        # PUT .phiacta/entry.yaml — blocked
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/.phiacta/entry.yaml",
            json={"content": content_b64},
            headers=headers,
        )
        assert resp.status_code == 404

        # PUT .phiacta/refs.yaml — blocked
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/.phiacta/refs.yaml",
            json={"content": content_b64},
            headers=headers,
        )
        assert resp.status_code == 404

        # PUT .phiacta/anything — blocked
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/.phiacta/custom.txt",
            json={"content": content_b64},
            headers=headers,
        )
        assert resp.status_code == 404

        # DELETE .phiacta/entry.yaml — blocked
        resp = await client.delete(
            f"/v1/entries/{entry_id}/files/.phiacta/entry.yaml",
            headers=headers,
        )
        assert resp.status_code == 404

        # GET .phiacta/entry.yaml — blocked (hidden from users)
        resp = await client.get(
            f"/v1/entries/{entry_id}/files/.phiacta/entry.yaml",
        )
        assert resp.status_code == 404

        # But normal files work fine
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/data.txt",
            json={"content": content_b64, "message": "Normal file"},
            headers=headers,
        )
        assert resp.status_code == 200


class TestHistoryAcrossOperations:
    """Write file → update metadata → verify history shows commits."""

    async def test_history_reflects_file_and_metadata_operations(
        self,
        client: httpx.AsyncClient,
        user_a: tuple[dict, str],
        e2e_session_factory,
        fake_git: FakeGitService,
    ) -> None:
        user, token = user_a
        headers = auth_header(token)
        entry = await create_entry(client, token, title="History Test")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # Write a file — generates a commit
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/README.md",
            json={
                "content": base64.b64encode(b"# History").decode(),
                "message": "Initial README",
            },
            headers=headers,
        )
        assert resp.status_code == 200

        # Update metadata — generates another commit
        _seed_entry_yaml(
            fake_git, entry_id, user["id"], "user-a", title="History Test",
        )
        resp = await client.patch(
            f"/v1/entries/{entry_id}",
            json={"title": "Updated History Test"},
            headers=headers,
        )
        assert resp.status_code == 200

        # Delete a file — generates another commit
        resp = await client.delete(
            f"/v1/entries/{entry_id}/files/README.md",
            headers=headers,
        )
        assert resp.status_code == 200

        # Verify FakeGitService recorded all 3 commits
        assert len(fake_git.commits) >= 3

        # Check commit messages
        messages = [c["message"] for c in fake_git.commits]
        assert any("Initial README" in m for m in messages)
        assert any("Update metadata" in m for m in messages)
        assert any("Delete" in m for m in messages)


class TestMultiUserAccessControl:
    """User B cannot write to user A's entry."""

    async def test_non_owner_blocked_from_all_writes(
        self,
        client: httpx.AsyncClient,
        user_a: tuple[dict, str],
        user_b: tuple[dict, str],
        e2e_session_factory,
        fake_git: FakeGitService,
    ) -> None:
        a_user, a_token = user_a
        _, b_token = user_b
        a_headers = auth_header(a_token)
        b_headers = auth_header(b_token)

        # User A creates entry
        entry = await create_entry(client, a_token, title="A's Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        content_b64 = base64.b64encode(b"content").decode()

        # User B cannot write files
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/README.md",
            json={"content": content_b64},
            headers=b_headers,
        )
        assert resp.status_code == 403

        # User B cannot delete files
        # First, user A writes a file
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/README.md",
            json={"content": content_b64},
            headers=a_headers,
        )
        assert resp.status_code == 200
        # Then user B tries to delete it
        resp = await client.delete(
            f"/v1/entries/{entry_id}/files/README.md",
            headers=b_headers,
        )
        assert resp.status_code == 403

        # User B cannot update metadata
        _seed_entry_yaml(
            fake_git, entry_id, a_user["id"], "user-a", title="A's Entry",
        )
        resp = await client.patch(
            f"/v1/entries/{entry_id}",
            json={"title": "Hijacked"},
            headers=b_headers,
        )
        assert resp.status_code == 403

        # User B cannot archive
        resp = await client.post(
            f"/v1/entries/{entry_id}/archive",
            headers=b_headers,
        )
        assert resp.status_code == 403

        # But user B CAN read files and entry details (public)
        resp = await client.get(f"/v1/entries/{entry_id}")
        assert resp.status_code == 200

        resp = await client.get(f"/v1/entries/{entry_id}/files/README.md")
        assert resp.status_code == 200


class TestMultiFileOperations:
    """Write multiple files, list them, delete some, verify."""

    async def test_multi_file_crud(
        self,
        client: httpx.AsyncClient,
        user_a: tuple[dict, str],
        e2e_session_factory,
    ) -> None:
        _, token = user_a
        headers = auth_header(token)
        entry = await create_entry(client, token)
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # Write 3 files
        files = {
            "README.md": b"# Test",
            "data/experiment.csv": b"x,y\n1,2\n3,4",
            "notes.txt": b"Some notes",
        }
        for path, content in files.items():
            resp = await client.put(
                f"/v1/entries/{entry_id}/files/{path}",
                json={"content": base64.b64encode(content).decode()},
                headers=headers,
            )
            assert resp.status_code == 200, f"Failed to write {path}: {resp.text}"

        # Read each file back
        for path, expected in files.items():
            resp = await client.get(f"/v1/entries/{entry_id}/files/{path}")
            assert resp.status_code == 200, f"Failed to read {path}"
            assert resp.content == expected

        # List files at root — should show README.md, data/ dir, notes.txt
        resp = await client.get(f"/v1/entries/{entry_id}/files")
        assert resp.status_code == 200
        names = {f["name"] for f in resp.json()}
        assert "README.md" in names
        assert "notes.txt" in names
        assert "data" in names

        # Delete one file
        resp = await client.delete(
            f"/v1/entries/{entry_id}/files/notes.txt",
            headers=headers,
        )
        assert resp.status_code == 200

        # Deleted file returns 404
        resp = await client.get(f"/v1/entries/{entry_id}/files/notes.txt")
        assert resp.status_code == 404

        # Other files still accessible
        resp = await client.get(f"/v1/entries/{entry_id}/files/README.md")
        assert resp.status_code == 200
        assert resp.content == b"# Test"


class TestRepoStatusTransitions:
    """Operations fail during provisioning, succeed after ready, fail during error."""

    async def test_operations_respect_repo_status(
        self,
        client: httpx.AsyncClient,
        user_a: tuple[dict, str],
        e2e_session_factory,
        fake_git: FakeGitService,
    ) -> None:
        _, token = user_a
        headers = auth_header(token)
        entry = await create_entry(client, token, title="Status Test")
        entry_id = entry["id"]

        content_b64 = base64.b64encode(b"test").decode()

        # --- Provisioning: all writes blocked ---
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/test.txt",
            json={"content": content_b64},
            headers=headers,
        )
        assert resp.status_code == 409

        resp = await client.post(
            f"/v1/entries/{entry_id}/archive", headers=headers,
        )
        assert resp.status_code == 409

        # --- Ready: writes succeed ---
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/test.txt",
            json={"content": content_b64},
            headers=headers,
        )
        assert resp.status_code == 200

        # --- Error: writes blocked again ---
        await set_entry_repo_status(e2e_session_factory, entry_id, "error")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/test2.txt",
            json={"content": content_b64},
            headers=headers,
        )
        assert resp.status_code == 409

        # But reads should still work (entry exists in DB)
        resp = await client.get(f"/v1/entries/{entry_id}")
        assert resp.status_code == 200


class TestListFiltering:
    """Archived and active entries filtered correctly in list endpoint."""

    async def test_status_filtering_across_lifecycle(
        self,
        client: httpx.AsyncClient,
        user_a: tuple[dict, str],
        e2e_session_factory,
        fake_git: FakeGitService,
    ) -> None:
        _, token = user_a
        headers = auth_header(token)

        # Create 3 entries
        e1 = await create_entry(client, token, title="Active One")
        e2 = await create_entry(client, token, title="To Archive")
        e3 = await create_entry(client, token, title="Active Two")

        for e in [e1, e2, e3]:
            await set_entry_repo_status(e2e_session_factory, e["id"], "ready")

        # Default list shows all 3
        resp = await client.get("/v1/entries")
        assert resp.status_code == 200
        assert resp.json()["total"] == 3

        # Archive one
        resp = await client.post(
            f"/v1/entries/{e2['id']}/archive", headers=headers,
        )
        assert resp.status_code == 200

        # Default list shows 2
        resp = await client.get("/v1/entries")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2
        ids = [item["id"] for item in resp.json()["items"]]
        assert e2["id"] not in ids

        # status=all shows 3
        resp = await client.get("/v1/entries", params={"status": "all"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 3

        # status=archived shows 1
        resp = await client.get("/v1/entries", params={"status": "archived"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["id"] == e2["id"]

        # Unarchive
        resp = await client.post(
            f"/v1/entries/{e2['id']}/unarchive", headers=headers,
        )
        assert resp.status_code == 200

        # Default list shows 3 again
        resp = await client.get("/v1/entries")
        assert resp.status_code == 200
        assert resp.json()["total"] == 3
