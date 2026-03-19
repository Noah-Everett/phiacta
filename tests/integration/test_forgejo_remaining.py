# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Integration tests covering entry update, archival, history, webhook HMAC
verification, content format, and cross-agent access.

These tests require the full Docker stack to be running:

    docker compose up -d

Run with:

    pytest tests/integration/test_forgejo_remaining.py -m forgejo

Each test registers its own agent (uuid4-prefixed handles/emails) and is
fully self-contained. No imports from phiacta source.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from uuid import uuid4

import httpx
import pytest

BASE_URL = "http://localhost:8000"

pytestmark = [pytest.mark.forgejo, pytest.mark.anyio]


# ---------------------------------------------------------------------------
# Helpers (mirrored from test_forgejo_entry_lifecycle.py)
# ---------------------------------------------------------------------------


async def register_agent(
    client: httpx.AsyncClient,
    handle: str | None = None,
    email: str | None = None,
    password: str = "Integration1!",
) -> dict:
    """Register a new agent and return the full auth response dict.

    Uses a uuid4 prefix by default so every call produces a unique agent.
    """
    uid = uuid4().hex[:12]
    resp = await client.post(
        "/v1/auth/register",
        json={
            "handle": handle or f"agent-{uid}",
            "email": email or f"agent-{uid}@example.com",
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
    content_format: str = "markdown",
) -> dict:
    """POST /v1/entries and return the created entry dict."""
    resp = await client.post(
        "/v1/entries",
        json={"title": title, "content_format": content_format},
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
    content_format: str = "markdown",
) -> tuple[str, str, dict]:
    """Register agent, create entry, wait for ready.

    Returns ``(token, entry_id, entry_dict)``.
    """
    auth = await register_agent(client)
    token = auth["access_token"]
    entry = await create_entry(client, token, title=title, content_format=content_format)
    entry_id = entry["id"]
    ready = await wait_for_ready(client, entry_id)
    return token, entry_id, ready


# ---------------------------------------------------------------------------
# Entry Update (PATCH /v1/entries/{id})
# ---------------------------------------------------------------------------


class TestEntryUpdate:
    """PATCH /v1/entries/{id} updates metadata via git-first write."""

    async def test_update_entry_title(self) -> None:
        """Create entry, wait ready, PATCH title, GET entry, verify title changed.

        Note: the PATCH writes to git and the DB is updated asynchronously via
        webhook ingestion, so we poll until the DB reflects the new title.
        """
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            token, entry_id, _ = await _setup_ready_entry(
                client, title="Original Title",
            )

            new_title = f"Updated Title {uuid4().hex[:8]}"
            patch_resp = await client.patch(
                f"/v1/entries/{entry_id}",
                json={"title": new_title},
                headers=_auth_header(token),
            )
            assert patch_resp.status_code == 200, (
                f"PATCH failed: {patch_resp.text}"
            )

            # The DB update is async via webhook ingestion; poll for up to 30s.
            updated_title: str | None = None
            for _ in range(30):
                await asyncio.sleep(1.0)
                get_resp = await client.get(f"/v1/entries/{entry_id}")
                assert get_resp.status_code == 200
                updated_title = get_resp.json().get("title")
                if updated_title == new_title:
                    break

            assert updated_title == new_title, (
                f"title did not update after PATCH.\n"
                f"Expected: {new_title!r}\n"
                f"Got: {updated_title!r}"
            )

    async def test_update_entry_tags(self) -> None:
        """PATCH tags on an entry, verify the field is updated."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            token, entry_id, _ = await _setup_ready_entry(
                client, title="Tags Update Test",
            )

            new_tags = ["physics", "quantum", "test"]
            patch_resp = await client.patch(
                f"/v1/entries/{entry_id}",
                json={"tags": new_tags},
                headers=_auth_header(token),
            )
            assert patch_resp.status_code == 200, (
                f"PATCH tags failed: {patch_resp.text}"
            )

            # Poll until tags are reflected in the DB.
            updated_tags: list | None = None
            for _ in range(30):
                await asyncio.sleep(1.0)
                get_resp = await client.get(f"/v1/entries/{entry_id}")
                assert get_resp.status_code == 200
                updated_tags = get_resp.json().get("tags")
                if updated_tags == new_tags:
                    break

            assert updated_tags == new_tags, (
                f"tags did not update after PATCH.\n"
                f"Expected: {new_tags!r}\n"
                f"Got: {updated_tags!r}"
            )

    async def test_update_non_owner_rejected(self) -> None:
        """A second agent trying to PATCH an entry they don't own gets 403."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            # Agent A creates the entry.
            token_a, entry_id, _ = await _setup_ready_entry(
                client, title="Non-Owner PATCH Test",
            )

            # Agent B registers separately.
            auth_b = await register_agent(client)
            token_b = auth_b["access_token"]

            patch_resp = await client.patch(
                f"/v1/entries/{entry_id}",
                json={"title": "Stolen Title"},
                headers=_auth_header(token_b),
            )
            assert patch_resp.status_code == 403, (
                f"Expected 403 for non-owner PATCH, "
                f"got {patch_resp.status_code}: {patch_resp.text}"
            )


# ---------------------------------------------------------------------------
# Archival (POST /v1/entries/{id}/archive  &  /unarchive)
# ---------------------------------------------------------------------------


class TestArchival:
    """Archive and unarchive endpoints."""

    async def test_archive_entry(self) -> None:
        """Create entry, wait ready, archive it, verify status='archived'."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            token, entry_id, _ = await _setup_ready_entry(
                client, title="Archive Test",
            )

            archive_resp = await client.post(
                f"/v1/entries/{entry_id}/archive",
                headers=_auth_header(token),
            )
            assert archive_resp.status_code == 200, (
                f"archive failed: {archive_resp.text}"
            )

            get_resp = await client.get(f"/v1/entries/{entry_id}")
            assert get_resp.status_code == 200
            assert get_resp.json()["status"] == "archived", (
                f"Expected status='archived', got: {get_resp.json()['status']!r}"
            )

    async def test_unarchive_entry(self) -> None:
        """Archive then unarchive an entry, verify status returns to 'active'."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            token, entry_id, _ = await _setup_ready_entry(
                client, title="Unarchive Test",
            )

            # Archive first.
            archive_resp = await client.post(
                f"/v1/entries/{entry_id}/archive",
                headers=_auth_header(token),
            )
            assert archive_resp.status_code == 200, (
                f"archive failed: {archive_resp.text}"
            )

            # Then unarchive.
            unarchive_resp = await client.post(
                f"/v1/entries/{entry_id}/unarchive",
                headers=_auth_header(token),
            )
            assert unarchive_resp.status_code == 200, (
                f"unarchive failed: {unarchive_resp.text}"
            )

            get_resp = await client.get(f"/v1/entries/{entry_id}")
            assert get_resp.status_code == 200
            assert get_resp.json()["status"] == "active", (
                f"Expected status='active' after unarchive, "
                f"got: {get_resp.json()['status']!r}"
            )

    async def test_archive_blocks_file_writes(self) -> None:
        """An archived entry rejects PUT file requests with 403."""
        content_b64 = base64.b64encode(b"should be blocked").decode()

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            token, entry_id, _ = await _setup_ready_entry(
                client, title="Archive Blocks Writes Test",
            )

            archive_resp = await client.post(
                f"/v1/entries/{entry_id}/archive",
                headers=_auth_header(token),
            )
            assert archive_resp.status_code == 200, (
                f"archive failed: {archive_resp.text}"
            )

            put_resp = await client.put(
                f"/v1/entries/{entry_id}/files/blocked.txt",
                json={"content": content_b64, "message": "Should be rejected"},
                headers=_auth_header(token),
            )
            assert put_resp.status_code == 403, (
                f"Expected 403 for PUT to archived entry, "
                f"got {put_resp.status_code}: {put_resp.text}"
            )

    async def test_archive_non_owner_rejected(self) -> None:
        """A non-owner trying to archive an entry gets 403."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            # Agent A creates the entry.
            _token_a, entry_id, _ = await _setup_ready_entry(
                client, title="Non-Owner Archive Test",
            )

            # Agent B tries to archive it.
            auth_b = await register_agent(client)
            token_b = auth_b["access_token"]

            archive_resp = await client.post(
                f"/v1/entries/{entry_id}/archive",
                headers=_auth_header(token_b),
            )
            assert archive_resp.status_code == 403, (
                f"Expected 403 for non-owner archive, "
                f"got {archive_resp.status_code}: {archive_resp.text}"
            )


# ---------------------------------------------------------------------------
# History (GET /v1/entries/{id}/history)
# ---------------------------------------------------------------------------


class TestEntryHistory:
    """GET /v1/entries/{id}/history returns commit list."""

    # NOTE: The history endpoint (GET /v1/entries/{id}/history) may currently
    # return 404 if the GitService.list_commits method is not yet wired up
    # in the running stack. If these tests fail with 404, that confirms the
    # history endpoint needs fixing before the tests will pass.

    async def test_list_commits(self) -> None:
        """Create entry, wait ready, write a file, GET history, verify
        at least 2 commits (initial provisioning commit + file write).
        """
        content_b64 = base64.b64encode(b"history trigger content").decode()

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            token, entry_id, _ = await _setup_ready_entry(
                client, title="History Test",
            )

            # Write a file to produce a second commit.
            put_resp = await client.put(
                f"/v1/entries/{entry_id}/files/notes.txt",
                json={"content": content_b64, "message": "Add notes.txt"},
                headers=_auth_header(token),
            )
            assert put_resp.status_code == 200, f"PUT failed: {put_resp.text}"

            history_resp = await client.get(f"/v1/entries/{entry_id}/history")
            assert history_resp.status_code == 200, (
                f"GET history failed: {history_resp.text}"
            )

            commits = history_resp.json()
            assert isinstance(commits, list), (
                f"Expected list of commits, got: {type(commits)}"
            )
            assert len(commits) >= 2, (
                f"Expected at least 2 commits (initial + file write), "
                f"got {len(commits)}: {commits}"
            )

            # Each commit should have at least a sha field.
            for commit in commits:
                assert "sha" in commit, (
                    f"Commit missing 'sha' field: {commit}"
                )

    async def test_list_commits_public(self) -> None:
        """History endpoint requires no authentication — public read."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            _token, entry_id, _ = await _setup_ready_entry(
                client, title="History Public Test",
            )

            # Request without any auth header.
            history_resp = await client.get(f"/v1/entries/{entry_id}/history")
            assert history_resp.status_code == 200, (
                f"GET history without auth failed: {history_resp.text}"
            )

            commits = history_resp.json()
            assert isinstance(commits, list), (
                f"Expected list of commits, got: {type(commits)}"
            )
            assert len(commits) >= 1, "Expected at least 1 commit in history"


# ---------------------------------------------------------------------------
# Webhook HMAC Verification
# ---------------------------------------------------------------------------


class TestWebhookHmac:
    """Webhook endpoint rejects requests with bad or missing signatures."""

    async def test_webhook_rejects_invalid_signature(self) -> None:
        """POST to /webhooks/forgejo with a fake HMAC signature returns 401 or 403."""
        payload = json.dumps({
            "ref": "refs/heads/main",
            "after": "a" * 40,
            "repository": {"name": str(uuid4())},
            "commits": [],
        }).encode()

        # Compute an HMAC with a wrong secret.
        fake_sig = hmac.new(
            b"wrong-secret", payload, hashlib.sha256
        ).hexdigest()

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            resp = await client.post(
                "/webhooks/forgejo",
                content=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Forgejo-Event": "push",
                    "X-Forgejo-Signature": fake_sig,
                },
            )
            assert resp.status_code in {401, 403}, (
                f"Expected 401 or 403 for invalid HMAC signature, "
                f"got {resp.status_code}: {resp.text}"
            )

    async def test_webhook_rejects_missing_signature(self) -> None:
        """POST to /webhooks/forgejo without X-Forgejo-Signature returns 401 or 403."""
        payload = json.dumps({
            "ref": "refs/heads/main",
            "after": "b" * 40,
            "repository": {"name": str(uuid4())},
            "commits": [],
        }).encode()

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            resp = await client.post(
                "/webhooks/forgejo",
                content=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Forgejo-Event": "push",
                    # Deliberately omit X-Forgejo-Signature.
                },
            )
            assert resp.status_code in {401, 403}, (
                f"Expected 401 or 403 for missing HMAC signature, "
                f"got {resp.status_code}: {resp.text}"
            )


# ---------------------------------------------------------------------------
# Content Format
# ---------------------------------------------------------------------------


class TestContentFormat:
    """Entry content_format controls which README file is provisioned."""

    async def test_entry_with_latex_format(self) -> None:
        """Create entry with content_format='latex', wait ready, verify
        README.tex exists in the file listing (not README.md).
        """
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            token, entry_id, _ = await _setup_ready_entry(
                client,
                title=f"LaTeX Entry {uuid4().hex[:8]}",
                content_format="latex",
            )

            files_resp = await client.get(f"/v1/entries/{entry_id}/files")
            assert files_resp.status_code == 200, files_resp.text
            file_names = [f["name"] for f in files_resp.json()]

            assert "README.tex" in file_names, (
                f"README.tex missing from latex entry listing: {file_names}"
            )
            assert "README.md" not in file_names, (
                f"README.md unexpectedly present in latex entry listing: {file_names}"
            )


# ---------------------------------------------------------------------------
# Cross-agent Access
# ---------------------------------------------------------------------------


class TestCrossAgentAccess:
    """Public read / owner-only write enforcement across agents."""

    async def test_other_agent_can_read_entry(self) -> None:
        """Agent A creates an entry; Agent B can GET it (public read, no auth)."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            # Agent A creates and readies the entry.
            _token_a, entry_id, _ = await _setup_ready_entry(
                client, title="Cross-Agent Read Test",
            )

            # Agent B registers and reads the entry without using Agent A's token.
            auth_b = await register_agent(client)
            token_b = auth_b["access_token"]

            get_resp = await client.get(
                f"/v1/entries/{entry_id}",
                headers=_auth_header(token_b),
            )
            assert get_resp.status_code == 200, (
                f"Agent B could not read Agent A's entry: {get_resp.text}"
            )
            assert get_resp.json()["id"] == entry_id

            # Also verify it works with no auth at all.
            get_no_auth = await client.get(f"/v1/entries/{entry_id}")
            assert get_no_auth.status_code == 200, (
                f"Unauthenticated GET failed: {get_no_auth.text}"
            )

    async def test_other_agent_cannot_write_files(self) -> None:
        """Agent A creates an entry; Agent B trying to PUT a file gets 403."""
        content_b64 = base64.b64encode(b"agent b injection").decode()

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            # Agent A creates and readies the entry.
            _token_a, entry_id, _ = await _setup_ready_entry(
                client, title="Cross-Agent Write Test",
            )

            # Agent B registers and attempts a file write.
            auth_b = await register_agent(client)
            token_b = auth_b["access_token"]

            put_resp = await client.put(
                f"/v1/entries/{entry_id}/files/injection.txt",
                json={"content": content_b64, "message": "Attempt injection"},
                headers=_auth_header(token_b),
            )
            assert put_resp.status_code == 403, (
                f"Expected 403 for cross-agent file write, "
                f"got {put_resp.status_code}: {put_resp.text}"
            )
