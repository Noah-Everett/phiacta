# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for entry read endpoints after entry minimization."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import phiacta.extensions.metadata.models  # noqa: F401
import phiacta.extensions.types.models  # noqa: F401
import phiacta.extensions.references.models  # noqa: F401

from tests.e2e.conftest import auth_header, create_entry, register_user, set_entry_repo_status

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


@pytest.fixture(autouse=True)
def _mount_extension_routers(client: httpx.AsyncClient) -> None:
    from phiacta.extensions.metadata import router as mr
    from phiacta.extensions.types import router as tr
    from phiacta.extensions.references import router as rr
    from phiacta.main import app as _app
    _app.include_router(mr, prefix="/v1/extensions/metadata", tags=["metadata"])
    _app.include_router(tr, prefix="/v1/extensions/types", tags=["types"])
    _app.include_router(rr, prefix="/v1/extensions/references", tags=["references"])
    yield  # type: ignore[misc]
    _app.routes[:] = [r for r in _app.routes if not (hasattr(r, "path") and (r.path.startswith("/v1/extensions/metadata") or r.path.startswith("/v1/extensions/types") or r.path.startswith("/v1/extensions/references")))]


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    auth = await register_user(client, handle=f"read-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def ready_entry(authed: AuthedFixture, e2e_session_factory: async_sessionmaker[AsyncSession]) -> tuple[AuthedFixture, dict]:
    client, _, token = authed
    entry = await create_entry(client, token, title="Read Test Entry")
    await set_entry_repo_status(e2e_session_factory, entry["id"], "ready")
    return authed, entry


class TestEntryDetail:
    async def test_detail_includes_metadata(self, ready_entry: tuple[AuthedFixture, dict]) -> None:
        (client, _, _), entry = ready_entry
        data = (await client.get(f"/v1/entries/{entry['id']}")).json()
        assert data["title"] == "Read Test Entry"

    async def test_detail_excludes_removed_columns(self, ready_entry: tuple[AuthedFixture, dict]) -> None:
        (client, _, _), entry = ready_entry
        data = (await client.get(f"/v1/entries/{entry['id']}")).json()
        assert "layout_hint" not in data
        assert "content_cache" not in data


class TestEntryList:
    async def test_list_items_include_title(self, ready_entry: tuple[AuthedFixture, dict]) -> None:
        (client, _, _), _ = ready_entry
        items = (await client.get("/v1/entries")).json()["items"]
        assert len(items) > 0
        for item in items:
            assert "title" in item

    async def test_list_items_exclude_removed_columns(self, ready_entry: tuple[AuthedFixture, dict]) -> None:
        (client, _, _), _ = ready_entry
        for item in (await client.get("/v1/entries")).json()["items"]:
            assert "layout_hint" not in item
            assert "content_cache" not in item
