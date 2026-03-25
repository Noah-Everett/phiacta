# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for search tool — entry_id + rank + optional metadata."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

import phiacta.extensions.metadata.models  # noqa: F401
import phiacta.extensions.types.models  # noqa: F401

from tests.e2e.conftest import auth_header, create_entry, register_user

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
    _app.routes[:] = [r for r in _app.routes if not (hasattr(r, "path") and (
        r.path.startswith("/v1/extensions/metadata") or r.path.startswith("/v1/extensions/types")
        or r.path.startswith("/v1/tools/search")
    ))]


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    auth = await register_user(client, handle=f"search-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


class TestSearchResultShape:
    async def test_search_endpoint_works(self, authed: AuthedFixture) -> None:
        client, _, token = authed
        resp = await client.get("/v1/tools/search/", params={"q": "quantum"})
        assert resp.status_code == 200
        assert "items" in resp.json()

    async def test_search_results_have_correct_fields(self, authed: AuthedFixture) -> None:
        client, _, token = authed
        resp = await client.get("/v1/tools/search/", params={"q": "anything"})
        assert resp.status_code == 200
        for item in resp.json().get("items", []):
            assert "entry_id" in item
            assert "rank" in item
            # Optional metadata fields present (may be null)
            assert "title" in item
            assert "summary" in item
            assert "entry_type" in item
            # Removed fields absent
            assert "layout_hint" not in item
            assert "content_cache" not in item
