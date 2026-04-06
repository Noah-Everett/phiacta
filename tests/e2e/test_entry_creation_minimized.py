# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for entry creation after entry minimization."""

from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from phiacta.core.models.entry import Entry
from phiacta.core.models.outbox import Outbox
import phiacta.extensions.metadata.models  # noqa: F401
import phiacta.extensions.types.models  # noqa: F401

from tests.e2e.conftest import auth_header, register_user

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


@pytest.fixture(autouse=True)
def _mount_extension_routers(client: httpx.AsyncClient) -> None:
    from phiacta.extensions.metadata import router as mr
    from phiacta.extensions.types import router as tr
    from phiacta.main import app as _app
    _app.include_router(mr, prefix="/v1/extensions/metadata", tags=["metadata"])
    _app.include_router(tr, prefix="/v1/extensions/types", tags=["types"])
    yield  # type: ignore[misc]
    _app.routes[:] = [r for r in _app.routes if not (hasattr(r, "path") and (r.path.startswith("/v1/extensions/metadata") or r.path.startswith("/v1/extensions/types")))]


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    auth = await register_user(client, username=f"create-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


class TestCompoundCreate:
    async def test_create_with_all_fields(self, authed: AuthedFixture) -> None:
        client, user, token = authed
        resp = await client.post("/v1/entries", json={"title": "Full", "summary": "A complete entry", "content": "# Hello", "content_format": "markdown", "entry_type": "claim"}, headers=auth_header(token))
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Full"
        assert data["summary"] == "A complete entry"
        assert data["entry_type"] == "claim"
        assert data["repo_status"] == "provisioning"

    async def test_create_with_minimal_fields(self, authed: AuthedFixture) -> None:
        client, _, token = authed
        resp = await client.post("/v1/entries", json={"title": "Minimal"}, headers=auth_header(token))
        assert resp.status_code == 201
        assert resp.json()["title"] == "Minimal"
        assert resp.json().get("entry_type") is None

    async def test_create_without_title_fails(self, authed: AuthedFixture) -> None:
        client, _, token = authed
        resp = await client.post("/v1/entries", json={"content_format": "markdown"}, headers=auth_header(token))
        assert resp.status_code == 422


class TestEntryRowMinimized:
    async def test_entry_model_has_no_removed_columns(self, authed: AuthedFixture, e2e_session_factory: async_sessionmaker[AsyncSession]) -> None:
        client, _, token = authed
        resp = await client.post("/v1/entries", json={"title": "Check"}, headers=auth_header(token))
        entry_id = UUID(resp.json()["id"])
        async with e2e_session_factory() as session:
            result = await session.execute(select(Entry).where(Entry.id == entry_id))
            entry = result.scalar_one()
            assert not hasattr(entry, "title")
            assert not hasattr(entry, "content_cache")
            assert hasattr(entry, "repo_name")


class TestResponseShape:
    async def test_response_excludes_removed_columns(self, authed: AuthedFixture) -> None:
        client, _, token = authed
        data = (await client.post("/v1/entries", json={"title": "Shape"}, headers=auth_header(token))).json()
        assert "layout_hint" not in data
        assert "content_cache" not in data
        assert "license" not in data
