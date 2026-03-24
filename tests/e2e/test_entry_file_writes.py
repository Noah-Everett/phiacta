# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for entry file write API (NEV-125).

Tests the full API contract for:
- PUT /v1/entries/{entry_id}/files/{path}  -- create or update a file
- DELETE /v1/entries/{entry_id}/files/{path}  -- delete a file

These endpoints require authentication and entry ownership. Tests use
the FakeGitService (injected via dependency overrides) to verify that
the correct data reaches the git service layer.
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
    set_entry_status,
)

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    """Register a user and return (client, user_data, token)."""
    uid = uuid4().hex[:8]
    auth = await register_user(
        client, handle=f"writer-{uid}"
    )
    return client, auth["user"], auth["access_token"]


def _b64(content: bytes | str) -> str:
    """Base64-encode content for the request body."""
    if isinstance(content, str):
        content = content.encode()
    return base64.b64encode(content).decode()


# ---------------------------------------------------------------------------
# PUT /v1/entries/{entry_id}/files/{path} -- Create or update a file
# ---------------------------------------------------------------------------


class TestPutFile:
    """Scenario: Authenticated entry owner writes a file."""

    async def test_put_creates_new_file(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT a new file returns 200 with commit SHA."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Put Create Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/README.md",
            json={"content": _b64("# Hello World")},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "sha" in data
        assert data["sha"]  # non-empty

        # Verify the file was stored in FakeGitService
        stored = fake_git.files.get((UUID(entry_id), "README.md"))
        assert stored == b"# Hello World"

    async def test_put_updates_existing_file(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT an existing file overwrites it and returns 200."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Put Update Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # Pre-populate file
        fake_git.files[(UUID(entry_id), "notes.txt")] = b"old content"

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/notes.txt",
            json={"content": _b64("new content")},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        assert fake_git.files[(UUID(entry_id), "notes.txt")] == b"new content"

    async def test_put_with_custom_commit_message(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT with a message field uses that as the commit message."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Custom Msg Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/data.csv",
            json={"content": _b64("a,b,c"), "message": "Add experiment data"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        # Verify the commit message was passed to FakeGitService
        assert any(
            c["message"] == "Add experiment data" for c in fake_git.commits
        )

    async def test_put_empty_content_creates_zero_byte_file(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT with content="" (empty base64) creates a zero-byte file."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Empty File Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/empty.txt",
            json={"content": ""},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        assert fake_git.files[(UUID(entry_id), "empty.txt")] == b""

    async def test_put_nested_directory_path(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT to a nested path like subdir/deep/file.txt works."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Nested Put Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/data/results/output.csv",
            json={"content": _b64("x,y\n1,2")},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        stored = fake_git.files.get((UUID(entry_id), "data/results/output.csv"))
        assert stored == b"x,y\n1,2"

    async def test_put_binary_content(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT with binary content (e.g., PNG bytes) stores correctly."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Binary Put Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        binary_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/image.png",
            json={"content": _b64(binary_data)},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        assert fake_git.files[(UUID(entry_id), "image.png")] == binary_data


class TestPutFileErrors:
    """Scenario: Error responses for the PUT file endpoint."""

    async def test_put_without_auth_returns_401(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT without a Bearer token returns 401."""
        client, _, token = authed
        entry = await create_entry(client, token, title="No Auth Put Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/README.md",
            json={"content": _b64("hello")},
            # No auth header
        )
        assert resp.status_code == 401

    async def test_put_by_non_owner_returns_403(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT by a different authenticated user returns 403."""
        client, _, token_a = authed
        entry = await create_entry(client, token_a, title="Non-Owner Put Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # Register a second user
        uid = uuid4().hex[:8]
        auth_b = await register_user(
            client, handle=f"other-{uid}"
        )
        token_b = auth_b["access_token"]

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/README.md",
            json={"content": _b64("hacked")},
            headers=auth_header(token_b),
        )
        assert resp.status_code == 403
        assert "author" in resp.json()["detail"].lower()

    async def test_put_archived_entry_returns_403(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT to an archived entry returns 403 'Entry is not editable'."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Archived Put Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")
        await set_entry_status(e2e_session_factory, entry_id, "archived")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/README.md",
            json={"content": _b64("hello")},
            headers=auth_header(token),
        )
        assert resp.status_code == 403
        assert "not editable" in resp.json()["detail"].lower()

    async def test_put_retracted_entry_returns_403(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT to a retracted entry returns 403 'Entry is not editable'."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Retracted Put Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")
        await set_entry_status(e2e_session_factory, entry_id, "retracted")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/README.md",
            json={"content": _b64("hello")},
            headers=auth_header(token),
        )
        assert resp.status_code == 403
        assert "not editable" in resp.json()["detail"].lower()

    async def test_put_nonexistent_entry_returns_404(
        self,
        authed: AuthedFixture,
    ) -> None:
        """PUT to a nonexistent entry returns 404."""
        client, _, token = authed
        fake_id = uuid4()

        resp = await client.put(
            f"/v1/entries/{fake_id}/files/README.md",
            json={"content": _b64("hello")},
            headers=auth_header(token),
        )
        assert resp.status_code == 404
        assert "entry" in resp.json()["detail"].lower()

    async def test_put_phiacta_entry_yaml_returns_404(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT to .phiacta/entry.yaml is blocked (returns 404)."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Phiacta Block Put")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/.phiacta/entry.yaml",
            json={"content": _b64("hacked: true")},
            headers=auth_header(token),
        )
        assert resp.status_code == 404

    async def test_put_phiacta_refs_returns_404(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT to .phiacta/refs.yaml is blocked (returns 404)."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Phiacta Refs Put")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/.phiacta/refs.yaml",
            json={"content": _b64("hacked: true")},
            headers=auth_header(token),
        )
        assert resp.status_code == 404

    async def test_put_repo_provisioning_returns_409(
        self,
        authed: AuthedFixture,
    ) -> None:
        """PUT when repo_status='provisioning' returns 409."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Provisioning Put Entry")
        entry_id = entry["id"]
        # Default repo_status is "provisioning"

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/README.md",
            json={"content": _b64("hello")},
            headers=auth_header(token),
        )
        assert resp.status_code == 409
        assert "not yet ready" in resp.json()["detail"].lower()

    async def test_put_repo_error_returns_409(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT when repo_status='error' returns 409."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Error Put Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "error")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/README.md",
            json={"content": _b64("hello")},
            headers=auth_header(token),
        )
        assert resp.status_code == 409

    async def test_put_invalid_base64_returns_400(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT with invalid base64 content returns 400."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Bad Base64 Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/README.md",
            json={"content": "not-valid-base64!!!@#$"},
            headers=auth_header(token),
        )
        assert resp.status_code == 400
        assert "base64" in resp.json()["detail"].lower()

    async def test_put_file_exceeding_size_limit_returns_400(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT with content exceeding max_file_size_bytes returns 400."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Oversized File Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # Default max is 25 MB; create content slightly over that
        oversized = b"x" * (25 * 1024 * 1024 + 1)
        content_b64 = base64.b64encode(oversized).decode()

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/big.bin",
            json={"content": content_b64},
            headers=auth_header(token),
        )
        assert resp.status_code == 400
        assert "exceeds maximum size" in resp.json()["detail"].lower()

    async def test_put_path_traversal_returns_400(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT with path traversal (..) returns 400."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Traversal Put Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/%2E%2E/etc/passwd",
            json={"content": _b64("hacked")},
            headers=auth_header(token),
        )
        assert resp.status_code == 400

    async def test_put_absolute_path_returns_400(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT with absolute path returns 400."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Absolute Put Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/%2Fetc%2Fpasswd",
            json={"content": _b64("hacked")},
            headers=auth_header(token),
        )
        assert resp.status_code == 400

    async def test_put_invalid_uuid_returns_422(
        self,
        authed: AuthedFixture,
    ) -> None:
        """PUT with malformed UUID returns 422."""
        client, _, token = authed

        resp = await client.put(
            "/v1/entries/not-a-uuid/files/README.md",
            json={"content": _b64("hello")},
            headers=auth_header(token),
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /v1/entries/{entry_id}/files/{path} -- Delete a file
# ---------------------------------------------------------------------------


class TestDeleteFile:
    """Scenario: Authenticated entry owner deletes a file."""

    async def test_delete_removes_file(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """DELETE a file returns 200 with commit SHA and removes it."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Delete Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # Pre-populate file
        fake_git.files[(UUID(entry_id), "old_data.csv")] = b"old,data"

        resp = await client.request(
            "DELETE",
            f"/v1/entries/{entry_id}/files/old_data.csv",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "sha" in data
        assert data["sha"]

        # Verify file was removed
        assert (UUID(entry_id), "old_data.csv") not in fake_git.files

    async def test_delete_with_custom_commit_message(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """DELETE with a message field uses that as the commit message."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Delete Msg Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        fake_git.files[(UUID(entry_id), "obsolete.txt")] = b"old stuff"

        resp = await client.request(
            "DELETE",
            f"/v1/entries/{entry_id}/files/obsolete.txt",
            json={"message": "Remove obsolete file"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        assert any(
            c["message"] == "Remove obsolete file" for c in fake_git.commits
        )


class TestDeleteFileErrors:
    """Scenario: Error responses for the DELETE file endpoint."""

    async def test_delete_without_auth_returns_401(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """DELETE without a Bearer token returns 401."""
        client, _, token = authed
        entry = await create_entry(client, token, title="No Auth Delete Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.request(
            "DELETE",
            f"/v1/entries/{entry_id}/files/README.md",
        )
        assert resp.status_code == 401

    async def test_delete_by_non_owner_returns_403(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """DELETE by a different user returns 403."""
        client, _, token_a = authed
        entry = await create_entry(client, token_a, title="Non-Owner Delete")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        fake_git.files[(UUID(entry_id), "README.md")] = b"content"

        uid = uuid4().hex[:8]
        auth_b = await register_user(
            client, handle=f"other-del-{uid}"
        )
        token_b = auth_b["access_token"]

        resp = await client.request(
            "DELETE",
            f"/v1/entries/{entry_id}/files/README.md",
            headers=auth_header(token_b),
        )
        assert resp.status_code == 403

    async def test_delete_archived_entry_returns_403(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """DELETE on an archived entry returns 403."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Archived Delete")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")
        await set_entry_status(e2e_session_factory, entry_id, "archived")

        fake_git.files[(UUID(entry_id), "README.md")] = b"content"

        resp = await client.request(
            "DELETE",
            f"/v1/entries/{entry_id}/files/README.md",
            headers=auth_header(token),
        )
        assert resp.status_code == 403
        assert "not editable" in resp.json()["detail"].lower()

    async def test_delete_nonexistent_entry_returns_404(
        self,
        authed: AuthedFixture,
    ) -> None:
        """DELETE on a nonexistent entry returns 404."""
        client, _, token = authed
        fake_id = uuid4()

        resp = await client.request(
            "DELETE",
            f"/v1/entries/{fake_id}/files/README.md",
            headers=auth_header(token),
        )
        assert resp.status_code == 404

    async def test_delete_nonexistent_file_returns_404(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """DELETE a file that doesn't exist returns 404."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Missing File Delete")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # Don't populate the file in fake_git
        resp = await client.request(
            "DELETE",
            f"/v1/entries/{entry_id}/files/nonexistent.txt",
            headers=auth_header(token),
        )
        assert resp.status_code == 404

    async def test_delete_phiacta_entry_yaml_returns_404(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """DELETE .phiacta/entry.yaml is blocked (returns 404)."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Phiacta Block Delete")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.request(
            "DELETE",
            f"/v1/entries/{entry_id}/files/.phiacta/entry.yaml",
            headers=auth_header(token),
        )
        assert resp.status_code == 404

    async def test_delete_repo_provisioning_returns_409(
        self,
        authed: AuthedFixture,
    ) -> None:
        """DELETE when repo_status='provisioning' returns 409."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Provisioning Delete")
        entry_id = entry["id"]

        resp = await client.request(
            "DELETE",
            f"/v1/entries/{entry_id}/files/README.md",
            headers=auth_header(token),
        )
        assert resp.status_code == 409

    async def test_delete_path_traversal_returns_400(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """DELETE with path traversal (..) returns 400."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Traversal Delete")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.request(
            "DELETE",
            f"/v1/entries/{entry_id}/files/%2E%2E/etc/passwd",
            headers=auth_header(token),
        )
        assert resp.status_code == 400

    async def test_delete_invalid_uuid_returns_422(
        self,
        authed: AuthedFixture,
    ) -> None:
        """DELETE with malformed UUID returns 422."""
        client, _, token = authed

        resp = await client.request(
            "DELETE",
            "/v1/entries/not-a-uuid/files/README.md",
            headers=auth_header(token),
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Path validation for writes (mirrors TestGetFileContentPathValidation)
# ---------------------------------------------------------------------------


class TestFileWritePathValidation:
    """Scenario: Path security for write endpoints."""

    async def test_put_dotdot_blocked(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT with leading ../ returns 400."""
        client, _, token = authed
        entry = await create_entry(client, token, title="PV1")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/%2E%2E/etc/passwd",
            json={"content": _b64("x")},
            headers=auth_header(token),
        )
        assert resp.status_code == 400

    async def test_put_middle_dotdot_blocked(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT with .. in the middle of path returns 400."""
        client, _, token = authed
        entry = await create_entry(client, token, title="PV2")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/subdir/%2E%2E/secret",
            json={"content": _b64("x")},
            headers=auth_header(token),
        )
        assert resp.status_code == 400

    async def test_put_absolute_path_blocked(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT with absolute path returns 400."""
        client, _, token = authed
        entry = await create_entry(client, token, title="PV3")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/%2Fetc%2Fpasswd",
            json={"content": _b64("x")},
            headers=auth_header(token),
        )
        assert resp.status_code == 400

    async def test_put_phiacta_directory_blocked(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT to .phiacta/entry.yaml returns 404."""
        client, _, token = authed
        entry = await create_entry(client, token, title="PV4")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/.phiacta/entry.yaml",
            json={"content": _b64("x")},
            headers=auth_header(token),
        )
        assert resp.status_code == 404

    async def test_put_phiacta_bare_blocked(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT to path exactly '.phiacta' returns 404."""
        client, _, token = authed
        entry = await create_entry(client, token, title="PV5")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/.phiacta",
            json={"content": _b64("x")},
            headers=auth_header(token),
        )
        assert resp.status_code == 404

    async def test_put_phiacta_similar_name_allowed(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT to '.phiacta_backup/file.txt' is NOT blocked."""
        client, _, token = authed
        entry = await create_entry(client, token, title="PV6")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/.phiacta_backup/file.txt",
            json={"content": _b64("allowed")},
            headers=auth_header(token),
        )
        assert resp.status_code == 200

    async def test_delete_phiacta_directory_blocked(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """DELETE .phiacta/entry.yaml returns 404."""
        client, _, token = authed
        entry = await create_entry(client, token, title="PV7")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.request(
            "DELETE",
            f"/v1/entries/{entry_id}/files/.phiacta/entry.yaml",
            headers=auth_header(token),
        )
        assert resp.status_code == 404

    async def test_put_url_encoded_dotdot_blocked(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Double-encoded path traversal (%252E%252E) is blocked."""
        client, _, token = authed
        entry = await create_entry(client, token, title="PV8")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/%252E%252E/etc/passwd",
            json={"content": _b64("x")},
            headers=auth_header(token),
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Lifecycle tests -- write then read, write then delete
# ---------------------------------------------------------------------------


class TestFileWriteLifecycle:
    """Scenario: Full lifecycle of file write operations."""

    async def test_put_then_read_returns_content(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT a file, then GET it via read endpoint -- content matches."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Lifecycle Read Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # PUT the file
        content = b"# Lifecycle Test\nThis is a test."
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/README.md",
            json={"content": _b64(content)},
            headers=auth_header(token),
        )
        assert resp.status_code == 200

        # GET the file (public, no auth needed)
        resp = await client.get(f"/v1/entries/{entry_id}/files/README.md")
        assert resp.status_code == 200
        assert resp.content == content

    async def test_put_then_delete_then_read_returns_404(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT a file, DELETE it, then GET returns 404."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Lifecycle Delete Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # PUT the file
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/temp.txt",
            json={"content": _b64("temporary")},
            headers=auth_header(token),
        )
        assert resp.status_code == 200

        # DELETE the file
        resp = await client.request(
            "DELETE",
            f"/v1/entries/{entry_id}/files/temp.txt",
            headers=auth_header(token),
        )
        assert resp.status_code == 200

        # GET should now return 404
        resp = await client.get(f"/v1/entries/{entry_id}/files/temp.txt")
        assert resp.status_code == 404

    async def test_put_twice_both_succeed(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """PUT a file twice (create then update) -- both return 200."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Lifecycle Update Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # First PUT (create)
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/analysis.py",
            json={"content": _b64("v1"), "message": "Initial version"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        sha1 = resp.json()["sha"]

        # Second PUT (update)
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/analysis.py",
            json={"content": _b64("v2"), "message": "Revised version"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        sha2 = resp.json()["sha"]

        # Different commits
        assert sha1 != sha2
        # Content is updated
        assert fake_git.files[(UUID(entry_id), "analysis.py")] == b"v2"
