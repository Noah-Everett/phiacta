# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for the types extension plugin."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import phiacta.extensions.types.models  # noqa: F401

from tests.e2e.conftest import (
    auth_header, create_entry, register_user, set_entry_repo_status,
)

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


@pytest.fixture(autouse=True)
def _mount_types_router(client: httpx.AsyncClient) -> None:
    from phiacta.extensions.types import router as types_router
    from phiacta.main import app as _app
    _app.include_router(types_router, prefix="/v1/extensions/types", tags=["types"])
    yield  # type: ignore[misc]
    _app.routes[:] = [r for r in _app.routes if not (hasattr(r, "path") and r.path.startswith("/v1/extensions/types"))]


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    auth = await register_user(client, handle=f"types-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def ready_entry(authed: AuthedFixture, e2e_session_factory: async_sessionmaker[AsyncSession]) -> tuple[AuthedFixture, dict]:
    client, _, token = authed
    entry = await create_entry(client, token, title="Types Test Entry")
    await set_entry_repo_status(e2e_session_factory, entry["id"], "ready")
    return authed, entry


class TestTypeOnCreation:
    async def test_entry_creation_with_type(self, authed: AuthedFixture) -> None:
        client, _, token = authed
        resp = await client.post("/v1/entries", json={"title": "Typed", "content_format": "markdown", "entry_type": "claim"}, headers=auth_header(token))
        assert resp.status_code == 201
        assert resp.json()["entry_type"] == "claim"

    async def test_entry_creation_without_type(self, authed: AuthedFixture) -> None:
        client, _, token = authed
        resp = await client.post("/v1/entries", json={"title": "Untyped", "content_format": "markdown"}, headers=auth_header(token))
        assert resp.status_code == 201
        assert resp.json().get("entry_type") is None


class TestGetType:
    async def test_get_type_for_typed_entry(self, authed: AuthedFixture, e2e_session_factory: async_sessionmaker[AsyncSession]) -> None:
        client, _, token = authed
        resp = await client.post("/v1/entries", json={"title": "For Get", "content_format": "markdown", "entry_type": "argument"}, headers=auth_header(token))
        entry_id = resp.json()["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")
        resp = await client.get("/v1/extensions/types/", params={"entry_id": entry_id})
        assert resp.status_code == 200
        assert resp.json()["entry_type"] == "argument"

    async def test_get_type_for_untyped_entry(self, ready_entry: tuple[AuthedFixture, dict]) -> None:
        (client, _, _), entry = ready_entry
        resp = await client.get("/v1/extensions/types/", params={"entry_id": entry["id"]})
        assert resp.status_code == 404

    async def test_get_type_nonexistent_entry(self, client: httpx.AsyncClient) -> None:
        resp = await client.get("/v1/extensions/types/", params={"entry_id": str(uuid4())})
        assert resp.status_code == 404


class TestPutType:
    async def test_put_type_on_untyped_entry(self, ready_entry: tuple[AuthedFixture, dict]) -> None:
        (client, _, token), entry = ready_entry
        resp = await client.put(f"/v1/extensions/types/{entry['id']}", json={"entry_type": "dataset"}, headers=auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["entry_type"] == "dataset"

    async def test_put_type_non_owner_rejected(self, ready_entry: tuple[AuthedFixture, dict], client: httpx.AsyncClient) -> None:
        (_, _, _), entry = ready_entry
        other = await register_user(client, handle=f"other-{uuid4().hex[:8]}")
        resp = await client.put(f"/v1/extensions/types/{entry['id']}", json={"entry_type": "hijack"}, headers=auth_header(other["access_token"]))
        assert resp.status_code == 403

    async def test_put_type_unauthenticated(self, ready_entry: tuple[AuthedFixture, dict]) -> None:
        (client, _, _), entry = ready_entry
        resp = await client.put(f"/v1/extensions/types/{entry['id']}", json={"entry_type": "nope"})
        assert resp.status_code == 401

    async def test_put_type_open_ended_string(self, ready_entry: tuple[AuthedFixture, dict]) -> None:
        (client, _, token), entry = ready_entry
        resp = await client.put(f"/v1/extensions/types/{entry['id']}", json={"entry_type": "custom-user-defined"}, headers=auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["entry_type"] == "custom-user-defined"


class TestLayoutHintRemoved:
    async def test_entry_response_no_layout_hint(self, ready_entry: tuple[AuthedFixture, dict]) -> None:
        (client, _, _), entry = ready_entry
        resp = await client.get(f"/v1/entries/{entry['id']}")
        assert "layout_hint" not in resp.json()
