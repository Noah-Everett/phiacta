# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for entry endpoints."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from tests.e2e.conftest import (
    FakeGitService,
    auth_header,
    create_entry,
    register_agent,
    set_entry_repo_status,
)

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    """Register an agent and return (client, agent_data, token)."""
    auth = await register_agent(client, handle="entry-test", email="entry@example.com")
    return client, auth["agent"], auth["access_token"]


class TestCreateEntry:
    async def test_create_entry(self, authed: AuthedFixture) -> None:
        client, agent, token = authed
        resp = await client.post("/v1/entries", json={
            "title": "Newton's First Law",
            "layout_hint": "law",
        }, headers=auth_header(token))
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Newton's First Law"
        assert data["layout_hint"] == "law"
        assert data["content_format"] == "markdown"
        assert data["status"] == "active"
        assert data["repo_status"] == "provisioning"
        assert data["created_by"] == agent["id"]

    async def test_create_entry_unauthenticated(self, client: httpx.AsyncClient) -> None:
        resp = await client.post("/v1/entries", json={
            "title": "Should Fail",
        })
        assert resp.status_code == 401

    async def test_create_entry_empty_title(self, authed: AuthedFixture) -> None:
        client, _, token = authed
        resp = await client.post("/v1/entries", json={
            "title": "",
        }, headers=auth_header(token))
        assert resp.status_code == 422

    async def test_create_entry_invalid_format(self, authed: AuthedFixture) -> None:
        client, _, token = authed
        resp = await client.post("/v1/entries", json={
            "title": "Bad Format",
            "content_format": "docx",
        }, headers=auth_header(token))
        assert resp.status_code == 422

    async def test_create_entry_with_all_fields(self, authed: AuthedFixture) -> None:
        client, _, token = authed
        resp = await client.post("/v1/entries", json={
            "title": "Full Entry",
            "content_format": "latex",
            "layout_hint": "theorem",
            "summary": "A complete entry with all fields.",
            "license": "CC-BY-4.0",
        }, headers=auth_header(token))
        assert resp.status_code == 201
        data = resp.json()
        assert data["content_format"] == "latex"
        assert data["summary"] == "A complete entry with all fields."
        assert data["license"] == "CC-BY-4.0"


class TestListEntries:
    async def test_list_entries_empty(self, client: httpx.AsyncClient) -> None:
        resp = await client.get("/v1/entries")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_list_entries_with_data(self, authed: AuthedFixture) -> None:
        client, _, token = authed
        headers = auth_header(token)
        await client.post("/v1/entries", json={"title": "Entry A"}, headers=headers)
        await client.post("/v1/entries", json={"title": "Entry B"}, headers=headers)

        resp = await client.get("/v1/entries")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    async def test_list_entries_filter_layout_hint(self, authed: AuthedFixture) -> None:
        client, _, token = authed
        headers = auth_header(token)
        await client.post("/v1/entries", json={
            "title": "A Law", "layout_hint": "law",
        }, headers=headers)
        await client.post("/v1/entries", json={
            "title": "A Theorem", "layout_hint": "theorem",
        }, headers=headers)

        resp = await client.get("/v1/entries", params={"layout_hint": "law"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "A Law"

    async def test_list_entries_pagination(self, authed: AuthedFixture) -> None:
        client, _, token = authed
        headers = auth_header(token)
        for i in range(5):
            await client.post("/v1/entries", json={"title": f"Entry {i}"}, headers=headers)

        resp = await client.get("/v1/entries", params={"limit": 2, "offset": 0})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] == 5


class TestGetEntry:
    async def test_get_entry(self, authed: AuthedFixture) -> None:
        client, _, token = authed
        create_resp = await client.post("/v1/entries", json={
            "title": "Fetch Me",
        }, headers=auth_header(token))
        entry_id = create_resp.json()["id"]

        resp = await client.get(f"/v1/entries/{entry_id}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Fetch Me"

    async def test_get_entry_not_found(self, client: httpx.AsyncClient) -> None:
        resp = await client.get(f"/v1/entries/{uuid4()}")
        assert resp.status_code == 404


class TestUpdateEntry:
    """Update tests -- PATCH now writes to git. Detailed tests in test_entry_update.py."""

    async def test_update_entry(
        self,
        authed: AuthedFixture,
        e2e_session_factory,
        fake_git: FakeGitService,
    ) -> None:
        client, agent, token = authed
        headers = auth_header(token)
        entry = await create_entry(client, token, title="Original")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        from uuid import UUID

        import yaml
        yaml_bytes = yaml.dump({
            "entry_id": f"ent_{entry_id}",
            "schema_version": 1,
            "title": "Original",
            "author": {"id": f"usr_{agent['id']}", "name": "entry-test"},
            "created_at": "2026-01-01T00:00:00",
            "content_format": "markdown",
        }, default_flow_style=False, allow_unicode=True, sort_keys=False).encode()
        fake_git.files[(UUID(entry_id), ".phiacta/entry.yaml")] = yaml_bytes

        resp = await client.patch(f"/v1/entries/{entry_id}", json={
            "title": "Updated",
        }, headers=headers)
        assert resp.status_code == 200
        updated = yaml.safe_load(fake_git.files[(UUID(entry_id), ".phiacta/entry.yaml")])
        assert updated["title"] == "Updated"

    async def test_update_entry_wrong_author(
        self, client: httpx.AsyncClient, e2e_session_factory,
    ) -> None:
        auth_a = await register_agent(client, handle="author-a", email="a@example.com")
        entry = await create_entry(client, auth_a["access_token"], title="A's Entry")
        await set_entry_repo_status(e2e_session_factory, entry["id"], "ready")

        auth_b = await register_agent(client, handle="author-b", email="b@example.com")
        resp = await client.patch(f"/v1/entries/{entry['id']}", json={
            "title": "Hijacked",
        }, headers=auth_header(auth_b["access_token"]))
        assert resp.status_code == 403

    async def test_update_entry_unauthenticated(
        self, authed: AuthedFixture, e2e_session_factory,
    ) -> None:
        client, _, token = authed
        entry = await create_entry(client, token, title="No Auth Update")
        await set_entry_repo_status(e2e_session_factory, entry["id"], "ready")

        resp = await client.patch(f"/v1/entries/{entry['id']}", json={
            "title": "Should Fail",
        })
        assert resp.status_code == 401


class TestEntryOutboxIntegration:
    async def test_create_entry_enqueues_outbox(self, authed: AuthedFixture) -> None:
        """Verify that creating an entry writes an outbox row for repo creation."""
        client, _, token = authed
        resp = await client.post("/v1/entries", json={
            "title": "Outbox Test",
        }, headers=auth_header(token))
        assert resp.status_code == 201
        entry = resp.json()
        # Entry should be in provisioning state
        assert entry["repo_status"] == "provisioning"
        assert entry["forgejo_repo_id"] is None
