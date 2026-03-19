# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Integration tests for edit proposals against real Forgejo.

These tests require the Docker stack to be running:
    docker compose up -d

Run with:
    pytest tests/integration/test_forgejo_edit_proposals.py -m forgejo
"""

from __future__ import annotations

import asyncio
import base64
from uuid import uuid4

import httpx
import pytest

BASE_URL = "http://localhost:8000"

pytestmark = [pytest.mark.forgejo, pytest.mark.anyio]


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: httpx.AsyncClient, prefix: str = "prop") -> tuple[dict, str]:
    """Register a unique agent. Returns (agent_data, token)."""
    uid = uuid4().hex[:8]
    resp = await client.post("/v1/auth/register", json={
        "handle": f"{prefix}_{uid}",
        "email": f"{prefix}_{uid}@example.com",
        "password": "S3cur3P@ssword!",
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["agent"], body["access_token"]


async def _wait_for_ready(
    client: httpx.AsyncClient, entry_id: str, token: str, timeout: int = 30,
) -> dict:
    """Poll until repo_status='ready' or timeout."""
    for _ in range(timeout):
        resp = await client.get(f"/v1/entries/{entry_id}", headers=_auth(token))
        data = resp.json()
        if data["repo_status"] == "ready":
            return data
        if data["repo_status"] == "error":
            pytest.fail(f"Entry {entry_id} errored")
        await asyncio.sleep(1)
    pytest.fail(f"Entry {entry_id} still provisioning after {timeout}s")


async def _create_ready_entry(
    client: httpx.AsyncClient, token: str, title: str = "Proposal Test",
) -> dict:
    """Create an entry and wait for ready."""
    resp = await client.post("/v1/entries", json={
        "title": title, "content_format": "markdown",
    }, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    return await _wait_for_ready(client, resp.json()["id"], token)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_create_proposal() -> None:
    """Non-owner can create a proposal, returns 201 with open state."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        _, owner_token = await _register(client, "owner")
        _, proposer_token = await _register(client, "proposer")
        entry = await _create_ready_entry(client, owner_token)

        resp = await client.post(
            f"/v1/entries/{entry['id']}/edits",
            json={
                "title": "Fix typo in README",
                "body": "Corrected spelling",
                "files": [{"path": "README.md", "content": _b64("# Fixed")}],
            },
            headers=_auth(proposer_token),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["state"] == "open"
        assert data["number"] >= 1
        assert data["title"] == "Fix typo in README"
        assert data["head_branch"].startswith("edit/")
        assert data["base_branch"] == "main"


async def test_list_proposals() -> None:
    """List returns created proposals."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        _, owner_token = await _register(client, "owner")
        _, proposer_token = await _register(client, "proposer")
        entry = await _create_ready_entry(client, owner_token)

        for i in range(2):
            resp = await client.post(
                f"/v1/entries/{entry['id']}/edits",
                json={
                    "title": f"Proposal {i}",
                    "files": [{"path": f"file{i}.txt", "content": _b64(f"content {i}")}],
                },
                headers=_auth(proposer_token),
            )
            assert resp.status_code == 201

        resp = await client.get(f"/v1/entries/{entry['id']}/edits")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2

        resp = await client.get(
            f"/v1/entries/{entry['id']}/edits", params={"state": "open"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) >= 2


async def test_merge_proposal() -> None:
    """Owner merges a proposal — file content changes to proposed version."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        _, owner_token = await _register(client, "owner")
        _, proposer_token = await _register(client, "proposer")
        entry = await _create_ready_entry(client, owner_token)

        # Create proposal that changes README
        resp = await client.post(
            f"/v1/entries/{entry['id']}/edits",
            json={
                "title": "Rewrite README",
                "files": [{"path": "README.md", "content": _b64("# Rewritten by proposal")}],
            },
            headers=_auth(proposer_token),
        )
        assert resp.status_code == 201
        pr_number = resp.json()["number"]

        # Owner merges
        resp = await client.post(
            f"/v1/entries/{entry['id']}/edits/{pr_number}/merge",
            headers=_auth(owner_token),
        )
        assert resp.status_code == 200, resp.text

        # Verify content changed
        resp = await client.get(f"/v1/entries/{entry['id']}/files/README.md")
        assert resp.status_code == 200
        assert "Rewritten by proposal" in resp.text


async def test_close_proposal() -> None:
    """Owner closes a proposal — appears in closed list."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        _, owner_token = await _register(client, "owner")
        _, proposer_token = await _register(client, "proposer")
        entry = await _create_ready_entry(client, owner_token)

        resp = await client.post(
            f"/v1/entries/{entry['id']}/edits",
            json={
                "title": "Will be closed",
                "files": [{"path": "x.txt", "content": _b64("x")}],
            },
            headers=_auth(proposer_token),
        )
        assert resp.status_code == 201
        pr_number = resp.json()["number"]

        # Close
        resp = await client.post(
            f"/v1/entries/{entry['id']}/edits/{pr_number}/close",
            headers=_auth(owner_token),
        )
        assert resp.status_code == 200

        # Verify in closed list
        resp = await client.get(
            f"/v1/entries/{entry['id']}/edits", params={"state": "closed"},
        )
        assert resp.status_code == 200
        closed = resp.json()
        assert any(p["number"] == pr_number for p in closed)


async def test_merge_updates_entry_sha() -> None:
    """After merge, webhook updates current_head_sha."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        _, owner_token = await _register(client, "owner")
        _, proposer_token = await _register(client, "proposer")
        entry = await _create_ready_entry(client, owner_token)
        original_sha = entry["current_head_sha"]

        resp = await client.post(
            f"/v1/entries/{entry['id']}/edits",
            json={
                "title": "SHA test",
                "files": [{"path": "sha_test.txt", "content": _b64("trigger webhook")}],
            },
            headers=_auth(proposer_token),
        )
        assert resp.status_code == 201
        pr_number = resp.json()["number"]

        await client.post(
            f"/v1/entries/{entry['id']}/edits/{pr_number}/merge",
            headers=_auth(owner_token),
        )

        # Poll for SHA change — webhook delivery after merge can take time
        for _ in range(30):
            await asyncio.sleep(2)
            resp = await client.get(f"/v1/entries/{entry['id']}")
            if resp.json()["current_head_sha"] != original_sha:
                return
        pytest.fail(f"SHA did not change after merge (still {original_sha})")


async def test_non_owner_cannot_merge() -> None:
    """Non-owner gets 403 when trying to merge."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        _, owner_token = await _register(client, "owner")
        _, proposer_token = await _register(client, "proposer")
        entry = await _create_ready_entry(client, owner_token)

        resp = await client.post(
            f"/v1/entries/{entry['id']}/edits",
            json={
                "title": "Unauthorized merge attempt",
                "files": [{"path": "x.txt", "content": _b64("x")}],
            },
            headers=_auth(proposer_token),
        )
        assert resp.status_code == 201
        pr_number = resp.json()["number"]

        # Proposer tries to merge — should be 403
        resp = await client.post(
            f"/v1/entries/{entry['id']}/edits/{pr_number}/merge",
            headers=_auth(proposer_token),
        )
        assert resp.status_code == 403


async def test_phiacta_path_blocked_on_create() -> None:
    """Proposal with .phiacta/ file is rejected at creation."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        _, owner_token = await _register(client, "owner")
        _, proposer_token = await _register(client, "proposer")
        entry = await _create_ready_entry(client, owner_token)

        resp = await client.post(
            f"/v1/entries/{entry['id']}/edits",
            json={
                "title": "Sneaky .phiacta edit",
                "files": [{"path": ".phiacta/entry.yaml", "content": _b64("hacked: true")}],
            },
            headers=_auth(proposer_token),
        )
        assert resp.status_code == 400


async def test_proposal_lifecycle_state_transitions() -> None:
    """Open → merged: verify state via detail and list endpoints."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        _, owner_token = await _register(client, "owner")
        _, proposer_token = await _register(client, "proposer")
        entry = await _create_ready_entry(client, owner_token)

        # Create
        resp = await client.post(
            f"/v1/entries/{entry['id']}/edits",
            json={
                "title": "State transition test",
                "files": [{"path": "state.txt", "content": _b64("v1")}],
            },
            headers=_auth(proposer_token),
        )
        assert resp.status_code == 201
        pr_number = resp.json()["number"]
        assert resp.json()["state"] == "open"

        # Verify open in list
        resp = await client.get(
            f"/v1/entries/{entry['id']}/edits", params={"state": "open"},
        )
        assert any(p["number"] == pr_number for p in resp.json())

        # Merge
        resp = await client.post(
            f"/v1/entries/{entry['id']}/edits/{pr_number}/merge",
            headers=_auth(owner_token),
        )
        assert resp.status_code == 200

        # Verify merged in detail
        resp = await client.get(f"/v1/entries/{entry['id']}/edits/{pr_number}")
        assert resp.status_code == 200
        assert resp.json()["state"] == "merged"

        # Verify in merged list, not in open list
        resp = await client.get(
            f"/v1/entries/{entry['id']}/edits", params={"state": "merged"},
        )
        assert any(p["number"] == pr_number for p in resp.json())

        resp = await client.get(
            f"/v1/entries/{entry['id']}/edits", params={"state": "open"},
        )
        assert not any(p["number"] == pr_number for p in resp.json())
