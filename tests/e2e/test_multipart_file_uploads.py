# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for multipart/form-data file uploads (PHI-121).

Tests the full API contract for:
- PUT /v1/entries/{entry_id}/files/{path}  -- multipart upload (replaces JSON+base64)

The endpoint now accepts multipart/form-data with:
- `content` file part: the raw file bytes
- `message` form field (optional): commit message

These tests verify the complete migration from JSON+base64 to multipart.
Edit proposals stay as JSON+base64 and are NOT changed here.
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
)

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    """Register a user and return (client, user_data, token)."""
    uid = uuid4().hex[:8]
    auth = await register_user(client, handle=f"multipart-{uid}")
    return client, auth["user"], auth["access_token"]


def _multipart_kwargs(
    content: bytes,
    *,
    message: str | None = None,
    filename: str = "upload",
    content_type: str = "application/octet-stream",
) -> dict:
    """Build httpx kwargs for a multipart file upload request.

    Returns a dict with `files` and optionally `data` keys suitable for
    passing to `client.put(...)`.
    """
    kwargs: dict = {
        "files": {"content": (filename, content, content_type)},
    }
    if message is not None:
        kwargs["data"] = {"message": message}
    return kwargs


# ---------------------------------------------------------------------------
# PUT /v1/entries/{entry_id}/files/{path} -- Multipart upload happy paths
# ---------------------------------------------------------------------------


class TestMultipartPutFile:
    """Scenario: Authenticated entry owner writes a file via multipart upload."""

    async def test_multipart_upload_creates_new_text_file(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario: Upload a plain text file via multipart and verify it is stored.

        The response must include a non-empty commit SHA, and the file bytes
        stored in FakeGitService must match exactly what was uploaded.
        """
        client, _, token = authed
        entry = await create_entry(client, token, title="Multipart Text Upload")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        text_content = b"# Hello from multipart\n\nThis is a test."
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/README.md",
            headers=auth_header(token),
            **_multipart_kwargs(text_content),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "sha" in data
        assert isinstance(data["sha"], str)
        assert len(data["sha"]) > 0

        stored = fake_git.files.get((UUID(entry_id), "README.md"))
        assert stored == text_content

    async def test_multipart_upload_binary_png_bytes(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario: Upload binary PNG-like content and verify exact byte preservation.

        Binary data must survive multipart encoding without corruption.
        """
        client, _, token = authed
        entry = await create_entry(client, token, title="Multipart Binary Upload")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # Realistic PNG header bytes + some high-byte content
        binary_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(range(256))
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/figures/diagram.png",
            headers=auth_header(token),
            **_multipart_kwargs(binary_data, content_type="image/png"),
        )
        assert resp.status_code == 200
        assert fake_git.files[(UUID(entry_id), "figures/diagram.png")] == binary_data

    async def test_multipart_upload_with_commit_message(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario: Upload with an explicit commit message, verify it is used."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Multipart Message Upload")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/data.csv",
            headers=auth_header(token),
            **_multipart_kwargs(b"a,b,c\n1,2,3", message="Add experiment data"),
        )
        assert resp.status_code == 200
        assert any(
            c["message"] == "Add experiment data" for c in fake_git.commits
        )

    async def test_multipart_upload_without_message_uses_default(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario: Upload without a message field, verify a default message is used."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Multipart Default Msg")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/notes.txt",
            headers=auth_header(token),
            **_multipart_kwargs(b"some notes"),
        )
        assert resp.status_code == 200
        assert len(fake_git.commits) >= 1
        assert fake_git.commits[-1]["message"] == "Update notes.txt"

    async def test_multipart_upload_empty_file(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario: Upload zero bytes, creating an empty file (valid)."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Multipart Empty File")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/empty.txt",
            headers=auth_header(token),
            **_multipart_kwargs(b""),
        )
        assert resp.status_code == 200
        assert fake_git.files[(UUID(entry_id), "empty.txt")] == b""

    async def test_multipart_upload_nested_directory_path(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario: Upload to a deeply nested path like data/results/output.csv."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Multipart Nested Path")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/data/results/output.csv",
            headers=auth_header(token),
            **_multipart_kwargs(b"x,y,z\n1,2,3\n4,5,6"),
        )
        assert resp.status_code == 200
        stored = fake_git.files.get((UUID(entry_id), "data/results/output.csv"))
        assert stored == b"x,y,z\n1,2,3\n4,5,6"

    async def test_multipart_upload_message_with_unicode_and_newlines(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario: Commit message with unicode and newlines is preserved."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Multipart Unicode Msg")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        msg = "Add results\n\nIncludes data from experiment"
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/results.txt",
            headers=auth_header(token),
            **_multipart_kwargs(b"data here", message=msg),
        )
        assert resp.status_code == 200
        assert any(c["message"] == msg for c in fake_git.commits)


# ---------------------------------------------------------------------------
# Multipart upload error paths
# ---------------------------------------------------------------------------


class TestMultipartPutFileErrors:
    """Scenario: Error responses for multipart file uploads."""

    async def test_multipart_missing_content_part_returns_422(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario: PUT without the required 'content' file part returns 422."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Missing Content Part")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # Send only a message form field, no file part
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/README.md",
            headers=auth_header(token),
            data={"message": "no content"},
        )
        assert resp.status_code == 422

    async def test_multipart_exceeds_max_size_returns_400(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario: Upload exceeding 25MB size limit is rejected with 400."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Oversized Multipart")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        oversized = b"x" * (25 * 1024 * 1024 + 1)
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/big.bin",
            headers=auth_header(token),
            **_multipart_kwargs(oversized),
        )
        assert resp.status_code == 400
        assert "exceeds maximum size" in resp.json()["detail"].lower()

    async def test_multipart_protected_path_entry_yaml_returns_404(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario: Upload to .phiacta/entry.yaml is rejected."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Protected Path Multipart")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/.phiacta/entry.yaml",
            headers=auth_header(token),
            **_multipart_kwargs(b"hacked: true"),
        )
        assert resp.status_code == 404

    async def test_multipart_path_traversal_returns_400(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario: Path traversal via ../etc/passwd is rejected."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Traversal Multipart")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/%2E%2E/etc/passwd",
            headers=auth_header(token),
            **_multipart_kwargs(b"hacked"),
        )
        assert resp.status_code == 400

    async def test_multipart_without_auth_returns_401(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario: Multipart upload without authentication returns 401."""
        client, _, token = authed
        entry = await create_entry(client, token, title="No Auth Multipart")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/README.md",
            **_multipart_kwargs(b"hello"),
            # No auth header
        )
        assert resp.status_code == 401

    async def test_multipart_by_non_owner_returns_403(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario: Multipart upload by non-owner returns 403."""
        client, _, token_a = authed
        entry = await create_entry(client, token_a, title="Non-Owner Multipart")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        uid = uuid4().hex[:8]
        auth_b = await register_user(client, handle=f"other-mp-{uid}")
        token_b = auth_b["access_token"]

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/README.md",
            headers=auth_header(token_b),
            **_multipart_kwargs(b"hacked"),
        )
        assert resp.status_code == 403
        assert "author" in resp.json()["detail"].lower()

    async def test_multipart_json_body_rejected(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario: The old JSON+base64 format is no longer accepted (422).

        After migration, sending a JSON body with base64 content should fail
        because the endpoint now expects multipart/form-data.
        """
        client, _, token = authed
        entry = await create_entry(client, token, title="Old JSON Format")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        import base64

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/README.md",
            json={"content": base64.b64encode(b"hello").decode()},
            headers=auth_header(token),
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Lifecycle tests -- multipart upload then read, upload then overwrite
# ---------------------------------------------------------------------------


class TestMultipartLifecycle:
    """Scenario: Full lifecycle of multipart file operations."""

    async def test_multipart_upload_then_read_returns_exact_bytes(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario: Upload via multipart, then GET the file, content matches exactly."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Multipart Lifecycle Read")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        content = b"# Multipart Lifecycle Test\nLine two."
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/README.md",
            headers=auth_header(token),
            **_multipart_kwargs(content),
        )
        assert resp.status_code == 200

        # GET the file
        resp = await client.get(f"/v1/entries/{entry_id}/files/README.md")
        assert resp.status_code == 200
        assert resp.content == content

    async def test_multipart_upload_twice_updates_content(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario: Upload v1 then v2 via multipart, content and SHA both change."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Multipart Lifecycle Update")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # First upload
        resp1 = await client.put(
            f"/v1/entries/{entry_id}/files/analysis.py",
            headers=auth_header(token),
            **_multipart_kwargs(b"version 1", message="Initial version"),
        )
        assert resp1.status_code == 200
        sha1 = resp1.json()["sha"]

        # Second upload
        resp2 = await client.put(
            f"/v1/entries/{entry_id}/files/analysis.py",
            headers=auth_header(token),
            **_multipart_kwargs(b"version 2", message="Revised version"),
        )
        assert resp2.status_code == 200
        sha2 = resp2.json()["sha"]

        assert sha1 != sha2
        assert fake_git.files[(UUID(entry_id), "analysis.py")] == b"version 2"

    async def test_multipart_upload_then_delete_then_read_404(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario: Upload via multipart, delete, then GET returns 404."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Multipart Lifecycle Delete")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # Upload
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/temp.txt",
            headers=auth_header(token),
            **_multipart_kwargs(b"temporary data"),
        )
        assert resp.status_code == 200

        # Delete
        resp = await client.request(
            "DELETE",
            f"/v1/entries/{entry_id}/files/temp.txt",
            headers=auth_header(token),
        )
        assert resp.status_code == 200

        # Read should 404
        resp = await client.get(f"/v1/entries/{entry_id}/files/temp.txt")
        assert resp.status_code == 404

    async def test_multipart_commit_messages_appear_in_history(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario: Multiple multipart uploads with different messages are all recorded."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Multipart History")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        messages = ["First upload", "Second upload", "Third upload"]
        for i, msg in enumerate(messages):
            resp = await client.put(
                f"/v1/entries/{entry_id}/files/file_{i}.txt",
                headers=auth_header(token),
                **_multipart_kwargs(f"content {i}".encode(), message=msg),
            )
            assert resp.status_code == 200

        recorded_messages = [c["message"] for c in fake_git.commits]
        for msg in messages:
            assert msg in recorded_messages


# ---------------------------------------------------------------------------
# Error injection tests — ForgejoError / RepoNotFoundError paths
# ---------------------------------------------------------------------------


class TestMultipartErrorInjection:
    """Test 502 and 404 error paths using FakeGitService error injection."""

    async def test_forgejo_error_on_commit_returns_502(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """When GitService raises ForgejoError, endpoint returns 502."""
        from phiacta.core.services.git_service import ForgejoError

        client, _, token = authed
        entry = await create_entry(client, token, title="ForgejoError Test")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        fake_git._next_error = ForgejoError("Forgejo unavailable")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/test.txt",
            headers=auth_header(token),
            **_multipart_kwargs(b"content"),
        )
        assert resp.status_code == 502
        assert "git service unavailable" in resp.json()["detail"].lower()

    async def test_repo_not_found_on_commit_returns_404(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """When GitService raises RepoNotFoundError, endpoint returns 404."""
        from phiacta.core.services.git_service import RepoNotFoundError

        client, _, token = authed
        entry = await create_entry(client, token, title="RepoNotFound Test")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        fake_git._next_error = RepoNotFoundError("Repo missing")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/test.txt",
            headers=auth_header(token),
            **_multipart_kwargs(b"content"),
        )
        assert resp.status_code == 404
        assert "repository not found" in resp.json()["detail"].lower()

    async def test_forgejo_error_on_read_returns_502(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """When GitService raises ForgejoError on read, endpoint returns 502."""
        from phiacta.core.services.git_service import ForgejoError

        client, _, token = authed
        entry = await create_entry(client, token, title="Read ForgejoError")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        fake_git._next_error = ForgejoError("Forgejo unavailable")

        resp = await client.get(f"/v1/entries/{entry_id}/files/test.txt")
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# Additional coverage — boundary values, author info, delete defaults
# ---------------------------------------------------------------------------


class TestMultipartAdditionalCoverage:
    """Additional tests from the audit — boundary values, author info, etc."""

    async def test_exact_max_size_is_accepted(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Upload exactly max_file_size_bytes (25MB) is accepted."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Exact Max Size")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        exact_max = b"x" * (25 * 1024 * 1024)
        resp = await client.put(
            f"/v1/entries/{entry_id}/files/max.bin",
            headers=auth_header(token),
            **_multipart_kwargs(exact_max),
        )
        assert resp.status_code == 200

    async def test_commit_has_correct_author_info(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Commit author uses the user's handle and phiacta.local email."""
        client, user, token = authed
        entry = await create_entry(client, token, title="Author Info Test")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        resp = await client.put(
            f"/v1/entries/{entry_id}/files/auth.txt",
            headers=auth_header(token),
            **_multipart_kwargs(b"content", message="Check author"),
        )
        assert resp.status_code == 200
        commit = fake_git.commits[-1]
        assert commit["author"].name == user["handle"]
        assert commit["author"].email == f"{user['id']}@phiacta.local"

    async def test_delete_without_message_uses_default(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """DELETE without a message body uses default 'Delete {path}'."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Delete Default Msg")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # Create file first
        fake_git.files[(UUID(entry_id), "old.txt")] = b"old"

        resp = await client.request(
            "DELETE",
            f"/v1/entries/{entry_id}/files/old.txt",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        assert fake_git.commits[-1]["message"] == "Delete old.txt"
