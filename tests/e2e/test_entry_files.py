# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for entry file read API (NEV-124).

Tests the full API contract for:
- GET /v1/entries/{entry_id}/files  -- list files at repo root
- GET /v1/entries/{entry_id}/files/{path}  -- read raw file content

These endpoints are public (no auth required). The tests use the
FakeGitService (injected via dependency overrides) to simulate files
in an entry's git repo, rather than hitting a real Forgejo instance.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
        client, username=f"files-{uid}"
    )
    return client, auth["user"], auth["access_token"]


# ---------------------------------------------------------------------------
# GET /v1/entries/{entry_id}/files -- List files at repo root
# ---------------------------------------------------------------------------


class TestListEntryFiles:
    """Scenario: User lists files at the root of an entry's repository."""

    async def test_list_files_returns_file_items(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /files returns 200 with file listing items from FakeGitService."""
        client, _, token = authed
        entry = await create_entry(client, token, title="File Listing Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # Populate the FakeGitService with explicit file listings
        fake_git.file_listings[(UUID(entry_id), "")] = [
            {"name": "README.md", "path": "README.md", "type": "file", "size": 1024},
            {"name": "data", "path": "data", "type": "dir", "size": 0},
        ]

        resp = await client.get(f"/v1/entries/{entry_id}/files")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2
        names = {item["name"] for item in data}
        assert "README.md" in names
        assert "data" in names

    async def test_list_files_includes_phiacta_directory(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """The .phiacta directory is included in file listings (not filtered)."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Phiacta Filter Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        fake_git.file_listings[(UUID(entry_id), "")] = [
            {"name": "README.md", "path": "README.md", "type": "file", "size": 512},
            {"name": ".phiacta", "path": ".phiacta", "type": "dir", "size": 0},
            {"name": "notes.txt", "path": "notes.txt", "type": "file", "size": 100},
        ]

        resp = await client.get(f"/v1/entries/{entry_id}/files")
        assert resp.status_code == 200
        data = resp.json()
        names = [item["name"] for item in data]
        assert ".phiacta" in names
        assert "README.md" in names
        assert "notes.txt" in names
        assert len(data) == 3

    async def test_list_files_response_has_expected_fields(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Each item in the file listing has exactly {name, path, type, size}."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Fields Check Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        fake_git.file_listings[(UUID(entry_id), "")] = [
            {"name": "paper.tex", "path": "paper.tex", "type": "file", "size": 8192},
        ]

        resp = await client.get(f"/v1/entries/{entry_id}/files")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        item = data[0]
        assert set(item.keys()) == {"name", "path", "type", "size"}
        assert item["name"] == "paper.tex"
        assert item["path"] == "paper.tex"
        assert item["type"] == "file"
        assert item["size"] == 8192

    async def test_list_files_is_public(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /files does not require authentication -- no auth header needed."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Public Files Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        fake_git.file_listings[(UUID(entry_id), "")] = [
            {"name": "README.md", "path": "README.md", "type": "file", "size": 256},
        ]

        # Request without any auth header
        resp = await client.get(f"/v1/entries/{entry_id}/files")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_list_files_only_phiacta_returns_phiacta(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Entry with only .phiacta dir returns that dir in the listing."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Empty Repo Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        fake_git.file_listings[(UUID(entry_id), "")] = [
            {"name": ".phiacta", "path": ".phiacta", "type": "dir", "size": 0},
        ]

        resp = await client.get(f"/v1/entries/{entry_id}/files")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == ".phiacta"

    async def test_list_files_includes_directories(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Both files and directories appear in the listing."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Mixed Listing Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        fake_git.file_listings[(UUID(entry_id), "")] = [
            {"name": "README.md", "path": "README.md", "type": "file", "size": 512},
            {"name": "src", "path": "src", "type": "dir", "size": 0},
            {"name": "data", "path": "data", "type": "dir", "size": 0},
            {"name": "Makefile", "path": "Makefile", "type": "file", "size": 2048},
        ]

        resp = await client.get(f"/v1/entries/{entry_id}/files")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 4
        types = {item["name"]: item["type"] for item in data}
        assert types["README.md"] == "file"
        assert types["src"] == "dir"
        assert types["data"] == "dir"
        assert types["Makefile"] == "file"
        # Directories must have size 0
        sizes = {item["name"]: item["size"] for item in data}
        assert sizes["src"] == 0
        assert sizes["data"] == 0
        # Files must have positive size
        assert sizes["README.md"] == 512
        assert sizes["Makefile"] == 2048


class TestListEntryFilesErrors:
    """Scenario: Error responses for the file listing endpoint."""

    async def test_list_files_nonexistent_entry_returns_404(
        self, client: httpx.AsyncClient
    ) -> None:
        """GET /files with a valid UUID that does not exist returns 404."""
        fake_id = uuid4()
        resp = await client.get(f"/v1/entries/{fake_id}/files")
        assert resp.status_code == 404
        detail = resp.json()["detail"]
        # Must be the specific "Entry not found" message, not a generic 404
        assert "entry" in detail.lower()
        assert "not found" in detail.lower()

    async def test_list_files_invalid_uuid_returns_422(
        self, client: httpx.AsyncClient
    ) -> None:
        """GET /files with an invalid UUID format returns 422."""
        resp = await client.get("/v1/entries/not-a-uuid/files")
        assert resp.status_code == 422

    async def test_list_files_repo_provisioning_returns_409(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Entry with repo_status='provisioning' returns 409."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Provisioning Entry")
        entry_id = entry["id"]
        # Entry is created with repo_status="provisioning" by default
        assert entry["repo_status"] == "provisioning"

        resp = await client.get(f"/v1/entries/{entry_id}/files")
        assert resp.status_code == 409
        assert "not yet ready" in resp.json()["detail"].lower()

    async def test_list_files_repo_error_returns_409(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Entry with repo_status='error' returns 409."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Error Status Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "error")

        resp = await client.get(f"/v1/entries/{entry_id}/files")
        assert resp.status_code == 409
        assert "not yet ready" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /v1/entries/{entry_id}/files/{path} -- Get raw file content
# ---------------------------------------------------------------------------


class TestGetFileContent:
    """Scenario: User retrieves raw file content from an entry's repository."""

    async def test_get_file_returns_content(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /files/README.md returns 200 with the raw file bytes."""
        client, _, token = authed
        entry = await create_entry(client, token, title="File Content Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        file_bytes = b"# Hello World\n\nThis is a test file."
        fake_git.files[(UUID(entry_id), "README.md")] = file_bytes

        resp = await client.get(f"/v1/entries/{entry_id}/files/README.md")
        assert resp.status_code == 200
        assert resp.content == file_bytes

    async def test_get_file_returns_correct_content_type_markdown(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """A .md file returns Content-Type: text/markdown."""
        client, _, token = authed
        entry = await create_entry(client, token, title="MD Content-Type Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        fake_git.files[(UUID(entry_id), "README.md")] = b"# Title"

        resp = await client.get(f"/v1/entries/{entry_id}/files/README.md")
        assert resp.status_code == 200
        content_type = resp.headers["content-type"]
        assert "text/markdown" in content_type

    async def test_get_file_returns_correct_content_type_python(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """A .py file returns Content-Type: text/x-python."""
        client, _, token = authed
        entry = await create_entry(client, token, title="PY Content-Type Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        fake_git.files[(UUID(entry_id), "script.py")] = b"print('hello')"

        resp = await client.get(f"/v1/entries/{entry_id}/files/script.py")
        assert resp.status_code == 200
        content_type = resp.headers["content-type"]
        assert "text/x-python" in content_type

    async def test_get_file_returns_octet_stream_for_unknown_extension(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """A file with an unknown extension returns application/octet-stream."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Unknown Ext Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        fake_git.files[(UUID(entry_id), "data.qzp")] = b"\x00\x01\x02"

        resp = await client.get(f"/v1/entries/{entry_id}/files/data.qzp")
        assert resp.status_code == 200
        content_type = resp.headers["content-type"]
        assert "application/octet-stream" in content_type

    async def test_get_file_returns_octet_stream_for_no_extension(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """A file without an extension (e.g., 'Makefile') returns application/octet-stream."""
        client, _, token = authed
        entry = await create_entry(client, token, title="No Ext Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        fake_git.files[(UUID(entry_id), "Makefile")] = b"all:\n\techo hello"

        resp = await client.get(f"/v1/entries/{entry_id}/files/Makefile")
        assert resp.status_code == 200
        content_type = resp.headers["content-type"]
        assert "application/octet-stream" in content_type

    async def test_get_file_is_public(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /files/{path} does not require authentication."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Public File Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        fake_git.files[(UUID(entry_id), "public.txt")] = b"public content"

        # No auth header
        resp = await client.get(f"/v1/entries/{entry_id}/files/public.txt")
        assert resp.status_code == 200
        assert resp.content == b"public content"

    async def test_get_file_nested_path(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /files/subdir/file.txt works for nested paths with slashes."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Nested Path Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        nested_content = b"nested file content"
        fake_git.files[(UUID(entry_id), "subdir/file.txt")] = nested_content

        resp = await client.get(f"/v1/entries/{entry_id}/files/subdir/file.txt")
        assert resp.status_code == 200
        assert resp.content == nested_content

    async def test_get_file_binary_content(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Binary file content (e.g., PNG) is returned correctly as raw bytes."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Binary Content Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # Minimal PNG header bytes
        png_bytes = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde"
        )
        fake_git.files[(UUID(entry_id), "image.png")] = png_bytes

        resp = await client.get(f"/v1/entries/{entry_id}/files/image.png")
        assert resp.status_code == 200
        assert resp.content == png_bytes
        content_type = resp.headers["content-type"]
        assert "image/png" in content_type


class TestGetFileContentErrors:
    """Scenario: Error responses for the file content endpoint."""

    async def test_get_file_nonexistent_entry_returns_404(
        self, client: httpx.AsyncClient
    ) -> None:
        """GET /files/{path} with a nonexistent entry UUID returns 404."""
        fake_id = uuid4()
        resp = await client.get(f"/v1/entries/{fake_id}/files/README.md")
        assert resp.status_code == 404
        detail = resp.json()["detail"]
        # Must be the specific "Entry not found" message, not a generic 404
        assert "entry" in detail.lower()
        assert "not found" in detail.lower()

    async def test_get_file_nonexistent_file_returns_404(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """GET /files/{path} for a file that does not exist returns 404."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Missing File Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # Do NOT populate fake_git with this file
        resp = await client.get(f"/v1/entries/{entry_id}/files/nonexistent.txt")
        assert resp.status_code == 404
        detail = resp.json()["detail"]
        # Must be the specific "File not found" message, not a generic 404
        assert "file" in detail.lower()
        assert "not found" in detail.lower()

    async def test_get_file_invalid_uuid_returns_422(
        self, client: httpx.AsyncClient
    ) -> None:
        """GET /files/{path} with an invalid UUID format returns 422."""
        resp = await client.get("/v1/entries/not-a-uuid/files/README.md")
        assert resp.status_code == 422

    async def test_get_file_repo_provisioning_returns_409(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Entry with repo_status='provisioning' returns 409."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Provisioning File Entry")
        entry_id = entry["id"]
        # Default repo_status is "provisioning"

        resp = await client.get(f"/v1/entries/{entry_id}/files/README.md")
        assert resp.status_code == 409
        assert "not yet ready" in resp.json()["detail"].lower()

    async def test_get_file_repo_error_returns_409(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Entry with repo_status='error' returns 409."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Error File Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "error")

        resp = await client.get(f"/v1/entries/{entry_id}/files/README.md")
        assert resp.status_code == 409
        assert "not yet ready" in resp.json()["detail"].lower()


class TestGetFileContentPathValidation:
    """Scenario: Path security -- traversal, absolute paths, and .phiacta filtering."""

    async def test_path_traversal_dotdot_returns_400(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Path with leading '../' returns 400 Invalid file path."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Traversal Entry 1")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # Use %2E%2E to prevent HTTP client from resolving ../
        resp = await client.get(f"/v1/entries/{entry_id}/files/%2E%2E/etc/passwd")
        assert resp.status_code == 400
        assert "invalid file path" in resp.json()["detail"].lower()

    async def test_path_traversal_middle_dotdot_returns_400(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Path with '..' in the middle returns 400 Invalid file path."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Traversal Entry 2")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # Use %2E%2E to prevent HTTP client from resolving ../
        resp = await client.get(
            f"/v1/entries/{entry_id}/files/subdir/%2E%2E/secret"
        )
        assert resp.status_code == 400
        assert "invalid file path" in resp.json()["detail"].lower()

    async def test_absolute_path_returns_400(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Path starting with '/' returns 400 Invalid file path."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Absolute Path Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # httpx may normalize leading slash; use %2F to ensure it's sent
        resp = await client.get(
            f"/v1/entries/{entry_id}/files/%2Fetc%2Fpasswd"
        )
        assert resp.status_code == 400
        assert "invalid file path" in resp.json()["detail"].lower()

    async def test_phiacta_entry_yaml_is_readable(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """All .phiacta/ paths are readable, including entry.yaml."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Phiacta Read Entry 1")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        fake_git.files[(UUID(entry_id), ".phiacta/entry.yaml")] = b"id: test"

        resp = await client.get(
            f"/v1/entries/{entry_id}/files/.phiacta/entry.yaml"
        )
        assert resp.status_code == 200
        assert resp.content == b"id: test"

    async def test_phiacta_bare_is_readable(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Path exactly '.phiacta' is readable."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Phiacta Read Entry 2")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        fake_git.files[(UUID(entry_id), ".phiacta")] = b"data"

        resp = await client.get(f"/v1/entries/{entry_id}/files/.phiacta")
        assert resp.status_code == 200
        assert resp.content == b"data"

    async def test_phiacta_refs_is_readable(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """All .phiacta/ paths including refs.yaml are readable."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Phiacta Read Entry 3")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        fake_git.files[(UUID(entry_id), ".phiacta/refs.yaml")] = b"refs: []"

        resp = await client.get(
            f"/v1/entries/{entry_id}/files/.phiacta/refs.yaml"
        )
        assert resp.status_code == 200
        assert resp.content == b"refs: []"

    async def test_phiacta_similar_name_allowed(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """A path like '.phiacta_backup/file.txt' is NOT blocked (only exact .phiacta)."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Phiacta Similar Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        fake_git.files[(UUID(entry_id), ".phiacta_backup/file.txt")] = b"allowed"

        resp = await client.get(
            f"/v1/entries/{entry_id}/files/.phiacta_backup/file.txt"
        )
        # Should NOT be blocked by .phiacta filtering.
        # It returns 200 (file found) because FakeGitService has the file.
        assert resp.status_code == 200
        assert resp.content == b"allowed"

    async def test_url_encoded_phiacta_is_readable(
        self,
        authed: AuthedFixture,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """URL-encoded '.phiacta/' paths are readable (all .phiacta/ is readable)."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Encoded Phiacta Entry")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        fake_git.files[(UUID(entry_id), ".phiacta/entry.yaml")] = b"id: test"

        # URL-encoded path resolves to .phiacta/entry.yaml — readable
        resp = await client.get(
            f"/v1/entries/{entry_id}/files/%2Ephiacta/entry.yaml"
        )
        assert resp.status_code == 200
        assert resp.content == b"id: test"
