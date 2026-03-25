# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for search tool after entry minimization."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import phiacta.extensions.metadata.models  # noqa: F401
import phiacta.extensions.types.models  # noqa: F401

from tests.e2e.conftest import auth_header, create_entry, register_user, set_entry_repo_status

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


@pytest.fixture(autouse=True)
def _mount_routers(client: httpx.AsyncClient) -> None:
    from phiacta.extensions.metadata import router as mr
    from phiacta.extensions.types import router as tr
    from phiacta.tools.search.router import router as sr
    from phiacta.main import app as _app
    _app.include_router(mr, prefix="/v1/extensions/metadata", tags=["metadata"])
    _app.include_router(tr, prefix="/v1/extensions/types", tags=["types"])
    _app.include_router(sr, prefix="/v1/tools/search", tags=["search"])
    yield  # type: ignore[misc]
    _app.routes[:] = [r for r in _app.routes if not (hasattr(r, "path") and (r.path.startswith("/v1/extensions/metadata") or r.path.startswith("/v1/extensions/types") or r.path.startswith("/v1/tools/search")))]


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    auth = await register_user(client, handle=f"search-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


class TestSearchResultShape:
    async def test_search_results_include_title(self, authed: AuthedFixture, e2e_session_factory: async_sessionmaker[AsyncSession]) -> None:
        client, _, token = authed
        await create_entry(client, token, title="Quantum Entanglement")
        resp = await client.get("/v1/tools/search/", params={"q": "quantum"})
        assert resp.status_code == 200
        assert "items" in resp.json()

    async def test_search_results_no_removed_fields(self, authed: AuthedFixture) -> None:
        client, _, token = authed
        resp = await client.get("/v1/tools/search/", params={"q": "anything"})
        assert resp.status_code == 200
        for item in resp.json().get("items", []):
            assert "layout_hint" not in item
            assert "content_cache" not in item
