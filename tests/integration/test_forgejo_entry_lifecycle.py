# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Integration tests for the entry lifecycle against real Forgejo.

These tests require the full Docker stack to be running:

    docker compose up -d

Run with:

    pytest tests/integration/test_forgejo_entry_lifecycle.py -m forgejo

Each test registers its own user (uuid4-prefixed usernames) and creates
its own entries so tests are fully independent and can run in any order.

Do NOT import from phiacta source code -- all interaction is through the HTTP API.
"""

from __future__ import annotations

import asyncio
import base64
from uuid import uuid4

import httpx
import pytest

BASE_URL = "http://localhost:8000"

pytestmark = [pytest.mark.forgejo, pytest.mark.anyio]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def register_user(
    client: httpx.AsyncClient,
    username: str | None = None,
    password: str = "Integration1!",
) -> dict:
    """Register a new user and return the full auth response dict.

    Uses a uuid4 prefix by default so every call produces a unique user.
    """
    uid = uuid4().hex[:12]
    resp = await client.post(
        "/v1/auth/register",
        json={
            "username": username or f"user-{uid}",
            "password": password,
        },
    )
    assert resp.status_code == 201, f"register failed: {resp.text}"
    return resp.json()


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def create_entry(
    client: httpx.AsyncClient,
    token: str,
    *,
    title: str = "Integration Test Entry",
) -> dict:
    """POST /v1/entries and return the created entry dict."""
    resp = await client.post(
        "/v1/entries",
        json={"title": title, "content_format": "markdown"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 201, f"create_entry failed: {resp.text}"
    return resp.json()


async def wait_for_ready(
    client: httpx.AsyncClient,
    entry_id: str,
    *,
    timeout: int = 30,
    poll_interval: float = 1.0,
) -> dict:
    """Poll GET /v1/entries/{entry_id} until repo_status == 'ready' or timeout.

    Returns the entry dict when ready.  Raises on timeout or error state.
    """
    elapsed = 0.0
    while elapsed < timeout:
        resp = await client.get(f"/v1/entries/{entry_id}")
        assert resp.status_code == 200, f"get entry failed: {resp.text}"
        data = resp.json()
        if data["repo_status"] == "ready":
            return data
        if data["repo_status"] == "error":
            pytest.fail(f"Entry {entry_id} entered error state: {data}")
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
    pytest.fail(
        f"Entry {entry_id} did not reach repo_status='ready' within {timeout}s"
    )


async def _setup_ready_entry(
    client: httpx.AsyncClient,
    title: str = "Integration Test Entry",
) -> tuple[str, str, dict]:
    """Register user, create entry, wait for ready.

    Returns ``(token, entry_id, entry_dict)``.
    """
    auth = await register_user(client)
    token = auth["access_token"]
    entry = await create_entry(client, token, title=title)
    entry_id = entry["id"]
    ready = await wait_for_ready(client, entry_id)
    return token, entry_id, ready


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFullEntryLifecycle:
    """Register user -> create entry -> provision -> verify ready state and files."""

    async def test_full_entry_lifecycle(self) -> None:
        """Register user, create entry, wait for provisioning, verify
        repo_status=ready, list files (README.md), read README content,
        and confirm it references the entry title.
        """
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            auth = await register_user(client)
            token = auth["access_token"]

            title = f"Lifecycle Test {uuid4().hex[:8]}"
            entry = await create_entry(client, token, title=title)
            entry_id = entry["id"]
            assert entry["repo_status"] == "provisioning"

            # Wait for repo to become ready
            ready = await wait_for_ready(client, entry_id)
            assert ready["repo_status"] == "ready"
            assert ready["forgejo_repo_id"] is not None

            # List files -- README.md must be present
            files_resp = await client.get(f"/v1/entries/{entry_id}/files")
            assert files_resp.status_code == 200, files_resp.text
            file_names = [f["name"] for f in files_resp.json()["items"]]
            assert "README.md" in file_names, (
                f"README.md missing from listing: {file_names}"
            )

            # Read README content -- must reference the entry title
            readme_resp = await client.get(
                f"/v1/entries/{entry_id}/files/README.md",
            )
            assert readme_resp.status_code == 200, readme_resp.text
            readme_text = readme_resp.text
            assert title in readme_text, (
                f"Entry title not found in README.md.\n"
                f"Title: {title!r}\nREADME:\n{readme_text}"
            )


class TestFileWriteAndRead:
    """Write a file to a ready entry and read it back."""

    async def test_file_write_and_read(self) -> None:
        """Create ready entry, PUT data.csv, list files, GET data.csv,
        and verify the content round-trips correctly.
        """
        csv_content = "id,value\n1,alpha\n2,beta\n3,gamma\n"
        csv_bytes = csv_content.encode()
        csv_b64 = base64.b64encode(csv_bytes).decode()

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            token, entry_id, _ = await _setup_ready_entry(
                client, title="File Write Test",
            )

            # Write data.csv
            put_resp = await client.put(
                f"/v1/entries/{entry_id}/files/data.csv",
                files={"content": ("file", base64.b64decode(csv_b64), "application/octet-stream")}, data={"message": "Add data.csv"},
                headers=_auth_header(token),
            )
            assert put_resp.status_code == 200, f"PUT failed: {put_resp.text}"
            put_data = put_resp.json()
            assert "sha" in put_data and put_data["sha"], (
                "PUT response missing sha"
            )

            # List files -- data.csv must appear
            files_resp = await client.get(f"/v1/entries/{entry_id}/files")
            assert files_resp.status_code == 200, files_resp.text
            file_names = [f["name"] for f in files_resp.json()["items"]]
            assert "data.csv" in file_names, (
                f"data.csv missing from listing: {file_names}"
            )

            # Read data.csv -- content must match
            get_resp = await client.get(
                f"/v1/entries/{entry_id}/files/data.csv",
            )
            assert get_resp.status_code == 200, f"GET failed: {get_resp.text}"
            assert get_resp.content == csv_bytes, (
                f"File content mismatch.\n"
                f"Expected: {csv_bytes!r}\nGot: {get_resp.content!r}"
            )


class TestFileDelete:
    """Write a file then delete it and verify it disappears."""

    async def test_file_delete(self) -> None:
        """Create ready entry, write temp.txt, delete it, verify it is gone."""
        content_b64 = base64.b64encode(b"temporary content").decode()

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            token, entry_id, _ = await _setup_ready_entry(
                client, title="File Delete Test",
            )

            # Write temp.txt
            put_resp = await client.put(
                f"/v1/entries/{entry_id}/files/temp.txt",
                files={"content": ("file", base64.b64decode(content_b64), "application/octet-stream")}, data={"message": "Add temp.txt"},
                headers=_auth_header(token),
            )
            assert put_resp.status_code == 200, f"PUT failed: {put_resp.text}"

            # Confirm file is listed
            files_resp = await client.get(f"/v1/entries/{entry_id}/files")
            assert files_resp.status_code == 200
            assert "temp.txt" in [f["name"] for f in files_resp.json()["items"]]

            # Delete temp.txt
            del_resp = await client.request(
                "DELETE",
                f"/v1/entries/{entry_id}/files/temp.txt",
                json={"message": "Remove temp.txt"},
                headers=_auth_header(token),
            )
            assert del_resp.status_code == 200, (
                f"DELETE failed: {del_resp.text}"
            )
            del_data = del_resp.json()
            assert "sha" in del_data and del_data["sha"], (
                "DELETE response missing sha"
            )

            # Confirm file is gone
            files_resp2 = await client.get(f"/v1/entries/{entry_id}/files")
            assert files_resp2.status_code == 200
            file_names2 = [f["name"] for f in files_resp2.json()["items"]]
            assert "temp.txt" not in file_names2, (
                f"temp.txt still present after deletion: {file_names2}"
            )


class TestEntryYamlProtected:
    """The .phiacta directory is write-protected from the user file API."""

    async def test_put_phiacta_entry_yaml_rejected(self) -> None:
        """PUT .phiacta/entry.yaml must return 400 or 404."""
        content_b64 = base64.b64encode(b"malicious: true").decode()

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            token, entry_id, _ = await _setup_ready_entry(
                client, title="Protected YAML PUT Test",
            )

            put_resp = await client.put(
                f"/v1/entries/{entry_id}/files/.phiacta/entry.yaml",
                json={
                    "content": content_b64,
                    "message": "Overwrite entry.yaml",
                },
                headers=_auth_header(token),
            )
            assert put_resp.status_code in {400, 404}, (
                f"Expected 400 or 404 for PUT .phiacta/entry.yaml, "
                f"got {put_resp.status_code}: {put_resp.text}"
            )

    async def test_delete_phiacta_entry_yaml_rejected(self) -> None:
        """DELETE .phiacta/entry.yaml must return 400 or 404."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            token, entry_id, _ = await _setup_ready_entry(
                client, title="Protected YAML DELETE Test",
            )

            del_resp = await client.request(
                "DELETE",
                f"/v1/entries/{entry_id}/files/.phiacta/entry.yaml",
                json={"message": "Delete entry.yaml"},
                headers=_auth_header(token),
            )
            assert del_resp.status_code in {400, 404}, (
                f"Expected 400 or 404 for DELETE .phiacta/entry.yaml, "
                f"got {del_resp.status_code}: {del_resp.text}"
            )


class TestWebhookIngestionUpdatesSha:
    """Writing a file triggers a Forgejo webhook that updates current_head_sha."""

    async def test_webhook_ingestion_updates_sha(self) -> None:
        """Create entry, wait for ready, note initial sha, write a new file,
        then poll until current_head_sha changes (webhook processed).
        """
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            token, entry_id, ready = await _setup_ready_entry(
                client, title="Webhook SHA Test",
            )

            initial_sha = ready.get("current_head_sha")

            # Write a new file to produce a real commit in Forgejo
            content_b64 = base64.b64encode(b"webhook trigger content").decode()
            put_resp = await client.put(
                f"/v1/entries/{entry_id}/files/trigger.txt",
                json={
                    "content": content_b64,
                    "message": "Trigger webhook",
                },
                headers=_auth_header(token),
            )
            assert put_resp.status_code == 200, f"PUT failed: {put_resp.text}"
            commit_sha = put_resp.json()["sha"]

            # Poll until current_head_sha changes or timeout (30s)
            updated_sha: str | None = initial_sha
            for _ in range(30):
                await asyncio.sleep(1.0)
                get_resp = await client.get(f"/v1/entries/{entry_id}")
                assert get_resp.status_code == 200
                updated_sha = get_resp.json().get("current_head_sha")
                if updated_sha != initial_sha:
                    break

            assert updated_sha != initial_sha, (
                f"current_head_sha did not change after file write.\n"
                f"Initial: {initial_sha!r}\n"
                f"Commit SHA from API: {commit_sha!r}\n"
                f"Still: {updated_sha!r}"
            )


class TestMultipleEntriesIsolated:
    """Two entries from the same user must not share files."""

    async def test_multiple_entries_isolated(self) -> None:
        """Create entry A and B, write different files to each, verify
        each entry only has its own files.
        """
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            auth = await register_user(client)
            token = auth["access_token"]

            entry_a = await create_entry(
                client, token, title="Isolation Test A",
            )
            entry_b = await create_entry(
                client, token, title="Isolation Test B",
            )

            await wait_for_ready(client, entry_a["id"])
            await wait_for_ready(client, entry_b["id"])

            content_b64 = base64.b64encode(b"isolated content").decode()

            # Write only.txt to A
            resp_a = await client.put(
                f"/v1/entries/{entry_a['id']}/files/only.txt",
                files={"content": ("file", base64.b64decode(content_b64), "application/octet-stream")}, data={"message": "Add only.txt"},
                headers=_auth_header(token),
            )
            assert resp_a.status_code == 200, f"PUT A failed: {resp_a.text}"

            # Write beta.txt to B
            resp_b = await client.put(
                f"/v1/entries/{entry_b['id']}/files/beta.txt",
                files={"content": ("file", base64.b64decode(content_b64), "application/octet-stream")}, data={"message": "Add beta.txt"},
                headers=_auth_header(token),
            )
            assert resp_b.status_code == 200, f"PUT B failed: {resp_b.text}"

            # Verify A has only.txt but not beta.txt
            files_a = await client.get(
                f"/v1/entries/{entry_a['id']}/files",
            )
            assert files_a.status_code == 200
            names_a = [f["name"] for f in files_a.json()["items"]]
            assert "only.txt" in names_a, (
                f"only.txt missing from A: {names_a}"
            )
            assert "beta.txt" not in names_a, (
                f"beta.txt leaked into A: {names_a}"
            )

            # Verify B has beta.txt but not only.txt
            files_b = await client.get(
                f"/v1/entries/{entry_b['id']}/files",
            )
            assert files_b.status_code == 200
            names_b = [f["name"] for f in files_b.json()["items"]]
            assert "beta.txt" in names_b, (
                f"beta.txt missing from B: {names_b}"
            )
            assert "only.txt" not in names_b, (
                f"only.txt leaked into B: {names_b}"
            )


class TestEntryMetadataFromYaml:
    """After provisioning, entry metadata comes from the metadata extension."""

    async def test_entry_metadata_from_yaml(self) -> None:
        """Create entry with a title, wait for ready, verify the title
        matches. entry.yaml is identity-only (entry_id, schema_version),
        so the title comes from the metadata extension, not entry.yaml.
        """
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            auth = await register_user(client)
            token = auth["access_token"]

            title = f"Metadata YAML Test {uuid4().hex[:8]}"
            entry = await create_entry(client, token, title=title)
            entry_id = entry["id"]

            # Wait for repo to be ready (entry.yaml written and ingested)
            ready = await wait_for_ready(client, entry_id)

            # Title must match what was requested at creation — it is
            # stored in the metadata extension, not in entry.yaml.
            assert ready["title"] == title, (
                f"title mismatch: expected {title!r}, got {ready['title']!r}"
            )
