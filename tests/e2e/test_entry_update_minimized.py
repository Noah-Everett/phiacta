# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for entry update after entry minimization."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import phiacta.extensions.metadata.models  # noqa: F401

from tests.e2e.conftest import auth_header, create_entry, register_user, set_entry_repo_status

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


@pytest.fixture(autouse=True)
def _mount_metadata_router(client: httpx.AsyncClient) -> None:
    from phiacta.extensions.metadata import router as mr
    from phiacta.main import app as _app
    _app.include_router(mr, prefix="/v1/extensions/metadata", tags=["metadata"])
    yield  # type: ignore[misc]
    _app.routes[:] = [r for r in _app.routes if not (hasattr(r, "path") and r.path.startswith("/v1/extensions/metadata"))]


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    auth = await register_user(client, username=f"update-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def ready_entry(authed: AuthedFixture, e2e_session_factory: async_sessionmaker[AsyncSession]) -> tuple[AuthedFixture, dict]:
    client, _, token = authed
    entry = await create_entry(client, token, title="Update Test Entry")
    await set_entry_repo_status(e2e_session_factory, entry["id"], "ready")
    return authed, entry


class TestMetadataUpdate:
    async def test_update_title_via_metadata_extension(self, ready_entry: tuple[AuthedFixture, dict]) -> None:
        (client, _, token), entry = ready_entry
        resp = await client.put(f"/v1/extensions/metadata/{entry['id']}", json={"title": "Updated"}, headers=auth_header(token))
        assert resp.status_code == 200
        assert (await client.get(f"/v1/entries/{entry['id']}")).json()["title"] == "Updated"

    async def test_update_summary_via_patch(self, ready_entry: tuple[AuthedFixture, dict]) -> None:
        (client, _, token), entry = ready_entry
        resp = await client.patch(f"/v1/extensions/metadata/{entry['id']}", json={"summary": "New summary"}, headers=auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["title"] == "Update Test Entry"  # unchanged

    async def test_metadata_update_is_db_only(self, ready_entry: tuple[AuthedFixture, dict]) -> None:
        (client, _, token), entry = ready_entry
        await client.put(f"/v1/extensions/metadata/{entry['id']}", json={"title": "DB Only"}, headers=auth_header(token))
        assert (await client.get(f"/v1/entries/{entry['id']}")).json()["title"] == "DB Only"
