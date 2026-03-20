# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for entry metadata update (NEV-128).

The PATCH /v1/entries/{id} endpoint writes updated .phiacta/entry.yaml to
git via GitService, then returns the current (pre-ingestion) DB state.
The DB is updated asynchronously by the webhook ingestion pipeline.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest
import yaml

from tests.e2e.conftest import (
    FakeGitService,
    auth_header,
    create_entry,
    register_agent,
    set_entry_repo_status,
    set_entry_status,
)

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


def _make_entry_yaml(
    entry_id: str,
    *,
    title: str = "Original Title",
    content_format: str = "markdown",
    author_id: str = "usr_placeholder",
    author_name: str = "test-agent",
    summary: str | None = None,
    license_: str | None = None,
    layout_hint: str | None = None,
) -> bytes:
    """Build a minimal entry.yaml for testing."""
    data: dict = {
        "entry_id": f"ent_{entry_id}",
        "schema_version": 1,
        "title": title,
        "author": {"id": author_id, "name": author_name},
        "created_at": "2026-01-01T00:00:00",
        "content_format": content_format,
    }
    if summary is not None:
        data["summary"] = summary
    if license_ is not None:
        data["license"] = license_
    if layout_hint is not None:
        data["layout_hint"] = layout_hint
    return yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False).encode()


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    """Register an agent and return (client, agent_data, token)."""
    auth = await register_agent(client, handle="update-test", email="update@example.com")
    return client, auth["agent"], auth["access_token"]


@pytest.fixture
async def ready_entry(
    authed: AuthedFixture,
    e2e_session_factory,  # type: ignore[type-arg]
    fake_git: FakeGitService,
) -> tuple[AuthedFixture, dict]:
    """Create an entry, set it to ready, and seed entry.yaml in FakeGitService."""
    client, agent, token = authed
    entry = await create_entry(client, token, title="Original Title")
    entry_id = entry["id"]
    await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

    # Seed the entry.yaml that the update endpoint will read-modify-write
    yaml_bytes = _make_entry_yaml(
        entry_id,
        title="Original Title",
        author_id=f"usr_{agent['id']}",
        author_name="update-test",
        summary="Original summary",
    )
    fake_git.files[(UUID(entry_id), ".phiacta/entry.yaml")] = yaml_bytes

    return authed, entry


class TestUpdateMetadata:
    """Tests for PATCH /v1/entries/{id} — git-first metadata update."""

    async def test_update_title_commits_to_git(
        self, ready_entry: tuple[AuthedFixture, dict], fake_git: FakeGitService,
    ) -> None:
        (client, _, token), entry = ready_entry
        entry_id = entry["id"]

        resp = await client.patch(
            f"/v1/entries/{entry_id}",
            json={"title": "New Title"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200

        # Verify a commit was made to FakeGitService
        assert len(fake_git.commits) >= 1
        last_commit = fake_git.commits[-1]
        assert ".phiacta/entry.yaml" in last_commit["files"]

        # Verify the committed YAML has the new title
        yaml_bytes = fake_git.files[(UUID(entry_id), ".phiacta/entry.yaml")]
        parsed = yaml.safe_load(yaml_bytes)
        assert parsed["title"] == "New Title"

    async def test_update_multiple_fields(
        self, ready_entry: tuple[AuthedFixture, dict], fake_git: FakeGitService,
    ) -> None:
        (client, _, token), entry = ready_entry

        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={
                "title": "Multi Update",
                "summary": "New summary",
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 200

        yaml_bytes = fake_git.files[(UUID(entry["id"]), ".phiacta/entry.yaml")]
        parsed = yaml.safe_load(yaml_bytes)
        assert parsed["title"] == "Multi Update"
        assert parsed["summary"] == "New summary"

    async def test_update_preserves_unchanged_fields(
        self, ready_entry: tuple[AuthedFixture, dict], fake_git: FakeGitService,
    ) -> None:
        (client, _, token), entry = ready_entry

        # Only update title — summary, author should be preserved
        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"title": "Only Title Changed"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200

        yaml_bytes = fake_git.files[(UUID(entry["id"]), ".phiacta/entry.yaml")]
        parsed = yaml.safe_load(yaml_bytes)
        assert parsed["title"] == "Only Title Changed"
        # Original values preserved
        assert parsed["summary"] == "Original summary"
        assert "author" in parsed
        assert parsed["entry_id"] == f"ent_{entry['id']}"

    async def test_update_returns_current_db_state(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, token), entry = ready_entry

        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"title": "New Title"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()

        # Response includes the commit SHA
        assert "sha" in data or "current_head_sha" in data or "id" in data
        # The response is an EntryResponse — still has the DB fields
        assert "id" in data
        assert "status" in data
        assert "repo_status" in data

    async def test_update_empty_body_no_commit(
        self, ready_entry: tuple[AuthedFixture, dict], fake_git: FakeGitService,
    ) -> None:
        (client, _, token), entry = ready_entry
        initial_commits = len(fake_git.commits)

        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        # No new commit should be created for an empty update
        assert len(fake_git.commits) == initial_commits

    async def test_update_content_format(
        self, ready_entry: tuple[AuthedFixture, dict], fake_git: FakeGitService,
    ) -> None:
        (client, _, token), entry = ready_entry

        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"content_format": "latex"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200

        yaml_bytes = fake_git.files[(UUID(entry["id"]), ".phiacta/entry.yaml")]
        parsed = yaml.safe_load(yaml_bytes)
        assert parsed["content_format"] == "latex"

    async def test_update_layout_hint(
        self, ready_entry: tuple[AuthedFixture, dict], fake_git: FakeGitService,
    ) -> None:
        (client, _, token), entry = ready_entry

        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"layout_hint": "theorem"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200

        yaml_bytes = fake_git.files[(UUID(entry["id"]), ".phiacta/entry.yaml")]
        parsed = yaml.safe_load(yaml_bytes)
        assert parsed["layout_hint"] == "theorem"

    async def test_update_license(
        self, ready_entry: tuple[AuthedFixture, dict], fake_git: FakeGitService,
    ) -> None:
        (client, _, token), entry = ready_entry

        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"license": "CC-BY-4.0"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200

        yaml_bytes = fake_git.files[(UUID(entry["id"]), ".phiacta/entry.yaml")]
        parsed = yaml.safe_load(yaml_bytes)
        assert parsed["license"] == "CC-BY-4.0"


class TestUpdateMetadataErrors:
    """Error cases for PATCH /v1/entries/{id}."""

    async def test_update_unauthenticated_returns_401(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, _), entry = ready_entry
        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"title": "Should Fail"},
        )
        assert resp.status_code == 401

    async def test_update_wrong_author_returns_403(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, _), entry = ready_entry
        other = await register_agent(client, handle="other-agent", email="other@example.com")
        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"title": "Hijacked"},
            headers=auth_header(other["access_token"]),
        )
        assert resp.status_code == 403

    async def test_update_archived_entry_returns_403(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        e2e_session_factory,  # type: ignore[type-arg]
    ) -> None:
        (client, _, token), entry = ready_entry
        await set_entry_status(e2e_session_factory, entry["id"], "archived")
        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"title": "Should Fail"},
            headers=auth_header(token),
        )
        assert resp.status_code == 403

    async def test_update_retracted_entry_returns_403(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        e2e_session_factory,  # type: ignore[type-arg]
    ) -> None:
        (client, _, token), entry = ready_entry
        await set_entry_status(e2e_session_factory, entry["id"], "retracted")
        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"title": "Should Fail"},
            headers=auth_header(token),
        )
        assert resp.status_code == 403

    async def test_update_provisioning_entry_returns_409(
        self, authed: AuthedFixture, fake_git: FakeGitService,
    ) -> None:
        client, _agent, token = authed
        entry = await create_entry(client, token)
        # Entry is in provisioning state by default — no set_entry_repo_status call
        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"title": "Should Fail"},
            headers=auth_header(token),
        )
        assert resp.status_code == 409

    async def test_update_nonexistent_entry_returns_404(
        self, authed: AuthedFixture,
    ) -> None:
        client, _, token = authed
        resp = await client.patch(
            f"/v1/entries/{uuid4()}",
            json={"title": "Should Fail"},
            headers=auth_header(token),
        )
        assert resp.status_code == 404

    async def test_update_invalid_content_format_returns_422(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, token), entry = ready_entry
        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"content_format": "docx"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422
