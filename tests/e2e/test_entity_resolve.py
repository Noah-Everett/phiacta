# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for entity resolve endpoint (PHI-1)."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import phiacta.extensions.metadata.models  # noqa: F401
import phiacta.extensions.types.models  # noqa: F401
import phiacta.extensions.tags.models  # noqa: F401

from tests.e2e.conftest import auth_header, create_entry, register_user

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


@pytest.fixture(autouse=True)
def _mount_extension_routers(client: httpx.AsyncClient) -> None:
    from phiacta.extensions.metadata import router as mr
    from phiacta.extensions.types import router as tr
    from phiacta.extensions.tags import router as tagr
    from phiacta.main import app as _app
    _app.include_router(mr, prefix="/v1/extensions/metadata", tags=["metadata"])
    _app.include_router(tr, prefix="/v1/extensions/types", tags=["types"])
    _app.include_router(tagr, prefix="/v1/extensions/tags", tags=["tags"])
    yield  # type: ignore[misc]
    _app.routes[:] = [
        r for r in _app.routes
        if not (
            hasattr(r, "path")
            and any(
                r.path.startswith(p)
                for p in (
                    "/v1/extensions/metadata",
                    "/v1/extensions/types",
                    "/v1/extensions/tags",
                )
            )
        )
    ]


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    auth = await register_user(client, username=f"resolve-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


class TestResolveEntry:
    async def test_resolve_entry_returns_composed_data(
        self, authed: AuthedFixture,
    ) -> None:
        client, _, token = authed
        entry = await create_entry(
            client, token, title="Resolvable", entry_type="claim",
        )
        resp = await client.get(f"/v1/entities/{entry['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entity_type"] == "entry"
        assert data["title"] == "Resolvable"
        assert data["entry_type"] == "claim"

    async def test_resolve_entry_includes_tags(
        self, authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        from tests.e2e.conftest import set_entry_repo_status
        client, _, token = authed
        entry = await create_entry(client, token, title="Tagged Resolve")
        await set_entry_repo_status(e2e_session_factory, entry["id"], "ready")
        await client.put(
            f"/v1/extensions/tags/{entry['id']}",
            json={"tags": ["resolved"]},
            headers=auth_header(token),
        )
        data = (await client.get(f"/v1/entities/{entry['id']}")).json()
        assert data["tags"] == ["resolved"]


class TestResolveUser:
    async def test_resolve_user_returns_profile(
        self, authed: AuthedFixture,
    ) -> None:
        client, user, _ = authed
        resp = await client.get(f"/v1/entities/{user['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entity_type"] == "user"
        assert data["username"] == user["username"]


class TestResolveErrors:
    async def test_nonexistent_uuid_returns_404(
        self, client: httpx.AsyncClient,
    ) -> None:
        resp = await client.get(f"/v1/entities/{uuid4()}")
        assert resp.status_code == 404

    async def test_invalid_uuid_returns_422(
        self, client: httpx.AsyncClient,
    ) -> None:
        resp = await client.get("/v1/entities/not-a-uuid")
        assert resp.status_code == 422
