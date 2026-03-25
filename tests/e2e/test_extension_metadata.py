# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for the metadata extension plugin."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import phiacta.extensions.metadata.models  # noqa: F401

from tests.e2e.conftest import (
    auth_header, create_entry, register_user, set_entry_repo_status,
)

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


@pytest.fixture(autouse=True)
def _mount_metadata_router(client: httpx.AsyncClient) -> None:
    from phiacta.extensions.metadata import router as metadata_router
    from phiacta.main import app as _app
    _app.include_router(metadata_router, prefix="/v1/extensions/metadata", tags=["metadata"])
    yield  # type: ignore[misc]
    _app.routes[:] = [
        r for r in _app.routes
        if not (hasattr(r, "path") and r.path.startswith("/v1/extensions/metadata"))
    ]


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    uid = uuid4().hex[:8]
    auth = await register_user(client, handle=f"meta-{uid}")
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def ready_entry(
    authed: AuthedFixture, e2e_session_factory: async_sessionmaker[AsyncSession],
) -> tuple[AuthedFixture, dict]:
    client, _, token = authed
    entry = await create_entry(client, token, title="Metadata Test Entry")
    await set_entry_repo_status(e2e_session_factory, entry["id"], "ready")
    return authed, entry


class TestMetadataOnCreation:
    async def test_entry_creation_sets_metadata(self, ready_entry: tuple[AuthedFixture, dict]) -> None:
        (client, _, token), entry = ready_entry
        resp = await client.get("/v1/extensions/metadata/", params={"entry_id": entry["id"]})
        assert resp.status_code == 200
        assert resp.json()["title"] == "Metadata Test Entry"

    async def test_entry_creation_with_summary(self, authed: AuthedFixture) -> None:
        client, _, token = authed
        resp = await client.post("/v1/entries", json={"title": "With Summary", "summary": "Brief", "content_format": "markdown"}, headers=auth_header(token))
        assert resp.status_code == 201
        assert resp.json()["summary"] == "Brief"

    async def test_entry_creation_without_title_fails(self, authed: AuthedFixture) -> None:
        client, _, token = authed
        resp = await client.post("/v1/entries", json={"content_format": "markdown"}, headers=auth_header(token))
        assert resp.status_code == 422


class TestGetMetadata:
    async def test_get_metadata_returns_title_and_summary(self, ready_entry: tuple[AuthedFixture, dict]) -> None:
        (client, _, _), entry = ready_entry
        resp = await client.get("/v1/extensions/metadata/", params={"entry_id": entry["id"]})
        assert resp.status_code == 200
        data = resp.json()
        assert "title" in data and "summary" in data and "created_at" in data

    async def test_get_metadata_nonexistent_entry(self, client: httpx.AsyncClient) -> None:
        resp = await client.get("/v1/extensions/metadata/", params={"entry_id": str(uuid4())})
        assert resp.status_code == 404

    async def test_get_metadata_no_auth_required(self, ready_entry: tuple[AuthedFixture, dict]) -> None:
        (client, _, _), entry = ready_entry
        resp = await client.get("/v1/extensions/metadata/", params={"entry_id": entry["id"]})
        assert resp.status_code == 200


class TestPutMetadata:
    async def test_put_metadata_updates_title(self, ready_entry: tuple[AuthedFixture, dict]) -> None:
        (client, _, token), entry = ready_entry
        resp = await client.put(f"/v1/extensions/metadata/{entry['id']}", json={"title": "Updated", "summary": "New"}, headers=auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated"

    async def test_put_metadata_title_required(self, ready_entry: tuple[AuthedFixture, dict]) -> None:
        (client, _, token), entry = ready_entry
        resp = await client.put(f"/v1/extensions/metadata/{entry['id']}", json={"summary": "No title"}, headers=auth_header(token))
        assert resp.status_code == 422

    async def test_put_metadata_non_owner_rejected(self, ready_entry: tuple[AuthedFixture, dict], client: httpx.AsyncClient) -> None:
        (_, _, _), entry = ready_entry
        other = await register_user(client, handle=f"other-{uuid4().hex[:8]}")
        resp = await client.put(f"/v1/extensions/metadata/{entry['id']}", json={"title": "Hijacked"}, headers=auth_header(other["access_token"]))
        assert resp.status_code == 403

    async def test_put_metadata_unauthenticated(self, ready_entry: tuple[AuthedFixture, dict]) -> None:
        (client, _, _), entry = ready_entry
        resp = await client.put(f"/v1/extensions/metadata/{entry['id']}", json={"title": "No Auth"})
        assert resp.status_code == 401

    async def test_put_metadata_nonexistent_entry(self, authed: AuthedFixture) -> None:
        client, _, token = authed
        resp = await client.put(f"/v1/extensions/metadata/{uuid4()}", json={"title": "Ghost"}, headers=auth_header(token))
        assert resp.status_code == 404


class TestPatchMetadata:
    async def test_patch_metadata_update_summary_only(self, ready_entry: tuple[AuthedFixture, dict]) -> None:
        (client, _, token), entry = ready_entry
        resp = await client.patch(f"/v1/extensions/metadata/{entry['id']}", json={"summary": "Patched"}, headers=auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["summary"] == "Patched"
        assert resp.json()["title"] == "Metadata Test Entry"

    async def test_patch_metadata_non_owner_rejected(self, ready_entry: tuple[AuthedFixture, dict], client: httpx.AsyncClient) -> None:
        (_, _, _), entry = ready_entry
        other = await register_user(client, handle=f"other-{uuid4().hex[:8]}")
        resp = await client.patch(f"/v1/extensions/metadata/{entry['id']}", json={"summary": "Nope"}, headers=auth_header(other["access_token"]))
        assert resp.status_code == 403


class TestEntryResponseComposition:
    async def test_entry_detail_includes_metadata_fields(self, ready_entry: tuple[AuthedFixture, dict]) -> None:
        (client, _, _), entry = ready_entry
        resp = await client.get(f"/v1/entries/{entry['id']}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Metadata Test Entry"

    async def test_entry_list_includes_metadata_fields(self, ready_entry: tuple[AuthedFixture, dict]) -> None:
        (client, _, _), _ = ready_entry
        resp = await client.get("/v1/entries")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) > 0
        for item in resp.json()["items"]:
            assert "title" in item

    async def test_entry_response_no_removed_columns(self, ready_entry: tuple[AuthedFixture, dict]) -> None:
        (client, _, _), entry = ready_entry
        data = (await client.get(f"/v1/entries/{entry['id']}")).json()
        assert "layout_hint" not in data
        assert "content_format" not in data
        assert "content_cache" not in data
        assert "license" not in data
