# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""PATCH /v1/entries/{id} rejects fields that the operation can't act on.

The legacy behavior was a silent no-op: sending ``{"content": "..."}`` to
PATCH returned 200 with the entry unchanged because no provider claimed the
``content`` field. That made agent-driven content updates fail invisibly.

These tests pin the new contract:
- ``content`` is rejected with a message pointing at the edit-proposals flow.
- ``content_format`` is rejected as immutable (it determines the git file
  extension and cannot change after create).
- Unknown extras (typos, fields for plugins that no longer exist) are still
  silently ignored — that's a separate concern preserved for forward-compat
  (see test_provider_dispatch_on_create.TestExtraFieldHandling).
"""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import phiacta.extensions.metadata.models  # noqa: F401

from tests.e2e.conftest import (
    auth_header,
    create_entry,
    register_user,
    set_entry_repo_status,
)

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    auth = await register_user(client, username=f"reject-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def ready_entry(
    authed: AuthedFixture,
    e2e_session_factory: async_sessionmaker[AsyncSession],
) -> tuple[AuthedFixture, dict]:
    client, _, token = authed
    entry = await create_entry(client, token, title="Reject Test Entry")
    await set_entry_repo_status(e2e_session_factory, entry["id"], "ready")
    return authed, entry


class TestRejectImmutableFields:
    async def test_patch_content_returns_422(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, token), entry = ready_entry
        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"content": "new content"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422, resp.text

    async def test_patch_content_error_mentions_edit_proposals(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """The 422 message must point the caller at the edit-proposals
        endpoint so an agent can self-correct without reading docs."""
        (client, _, token), entry = ready_entry
        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"content": "new content"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422
        body = resp.text.lower()
        assert "edit" in body and "proposal" in body
        assert "content" in body

    async def test_patch_content_format_returns_422(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, token), entry = ready_entry
        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"content_format": "latex"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422, resp.text

    async def test_patch_content_does_not_partially_apply(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """When PATCH includes content alongside a valid metadata field,
        the whole request must be rejected — not partially applied."""
        (client, _, token), entry = ready_entry
        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"content": "new content", "title": "Should Not Apply"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

        # Verify the title was NOT updated.
        get_resp = await client.get(f"/v1/entries/{entry['id']}")
        assert get_resp.json()["title"] == "Reject Test Entry"


class TestUnknownExtrasStillIgnored:
    """Pin the contract: unknown extras are silently dropped on update
    (matches the create-side behavior for plugin forward-compat). The
    immutable-field rejection above is targeted, not a strict-mode flip."""

    async def test_patch_unknown_field_returns_200(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, token), entry = ready_entry
        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"garbage_field": "anything", "title": "Updated Title"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["title"] == "Updated Title"
        assert "garbage_field" not in resp.json()
