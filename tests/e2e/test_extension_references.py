# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for the references extension plugin."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import phiacta.extensions.references.models  # noqa: F401

from tests.e2e.conftest import (
    auth_header, create_entry, register_user, set_entry_repo_status,
)

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


@pytest.fixture(autouse=True)
def _mount_references_router(client: httpx.AsyncClient) -> None:
    from phiacta.extensions.references import router as references_router
    from phiacta.main import app as _app
    _app.include_router(references_router, prefix="/v1/extensions/references", tags=["references"])
    yield  # type: ignore[misc]
    _app.routes[:] = [r for r in _app.routes if not (hasattr(r, "path") and r.path.startswith("/v1/extensions/references"))]


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    auth = await register_user(client, username=f"refs-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def two_entries(authed: AuthedFixture, e2e_session_factory: async_sessionmaker[AsyncSession]) -> tuple[AuthedFixture, dict, dict]:
    client, _, token = authed
    entry_a = await create_entry(client, token, title="Entry A")
    entry_b = await create_entry(client, token, title="Entry B")
    await set_entry_repo_status(e2e_session_factory, entry_a["id"], "ready")
    await set_entry_repo_status(e2e_session_factory, entry_b["id"], "ready")
    return authed, entry_a, entry_b


class TestCreateReference:
    async def test_create_reference(self, two_entries: tuple[AuthedFixture, dict, dict]) -> None:
        (client, _, token), a, b = two_entries
        resp = await client.post(f"/v1/extensions/references/{a['id']}", json={"target_entry_id": b["id"], "rel": "supports"}, headers=auth_header(token))
        assert resp.status_code == 201
        assert resp.json()["from_entry_id"] == a["id"]
        assert resp.json()["to_entry_id"] == b["id"]


class TestListReferences:
    async def test_list_outgoing(self, two_entries: tuple[AuthedFixture, dict, dict]) -> None:
        (client, _, token), a, b = two_entries
        await client.post(f"/v1/extensions/references/{a['id']}", json={"target_entry_id": b["id"], "rel": "supports"}, headers=auth_header(token))
        resp = await client.get("/v1/extensions/references/", params={"entry_id": a["id"], "direction": "outgoing"})
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

    async def test_list_incoming(self, two_entries: tuple[AuthedFixture, dict, dict]) -> None:
        (client, _, token), a, b = two_entries
        await client.post(f"/v1/extensions/references/{a['id']}", json={"target_entry_id": b["id"], "rel": "supports"}, headers=auth_header(token))
        resp = await client.get("/v1/extensions/references/", params={"entry_id": b["id"], "direction": "incoming"})
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1


class TestReferenceConstraints:
    async def test_duplicate_rejected(self, two_entries: tuple[AuthedFixture, dict, dict]) -> None:
        (client, _, token), a, b = two_entries
        body = {"target_entry_id": b["id"], "rel": "supports"}
        await client.post(f"/v1/extensions/references/{a['id']}", json=body, headers=auth_header(token))
        resp = await client.post(f"/v1/extensions/references/{a['id']}", json=body, headers=auth_header(token))
        assert resp.status_code == 409

    async def test_self_reference_rejected(self, two_entries: tuple[AuthedFixture, dict, dict]) -> None:
        (client, _, token), a, _ = two_entries
        resp = await client.post(f"/v1/extensions/references/{a['id']}", json={"target_entry_id": a["id"], "rel": "supports"}, headers=auth_header(token))
        assert resp.status_code == 400

    async def test_same_entries_different_rel_allowed(self, two_entries: tuple[AuthedFixture, dict, dict]) -> None:
        (client, _, token), a, b = two_entries
        r1 = await client.post(f"/v1/extensions/references/{a['id']}", json={"target_entry_id": b["id"], "rel": "supports"}, headers=auth_header(token))
        r2 = await client.post(f"/v1/extensions/references/{a['id']}", json={"target_entry_id": b["id"], "rel": "derives_from"}, headers=auth_header(token))
        assert r1.status_code == 201
        assert r2.status_code == 201


class TestDeleteReference:
    async def test_delete_reference(self, two_entries: tuple[AuthedFixture, dict, dict]) -> None:
        (client, _, token), a, b = two_entries
        create_resp = await client.post(f"/v1/extensions/references/{a['id']}", json={"target_entry_id": b["id"], "rel": "supports"}, headers=auth_header(token))
        ref_id = create_resp.json()["id"]
        resp = await client.delete(f"/v1/extensions/references/{ref_id}", headers=auth_header(token))
        assert resp.status_code == 204

    async def test_delete_non_owner_rejected(self, two_entries: tuple[AuthedFixture, dict, dict], client: httpx.AsyncClient) -> None:
        (_, _, token), a, b = two_entries
        create_resp = await client.post(f"/v1/extensions/references/{a['id']}", json={"target_entry_id": b["id"], "rel": "supports"}, headers=auth_header(token))
        ref_id = create_resp.json()["id"]
        other = await register_user(client, username=f"other-{uuid4().hex[:8]}")
        resp = await client.delete(f"/v1/extensions/references/{ref_id}", headers=auth_header(other["access_token"]))
        assert resp.status_code == 403


class TestReferenceAuth:
    async def test_create_non_owner_rejected(self, two_entries: tuple[AuthedFixture, dict, dict], client: httpx.AsyncClient) -> None:
        (_, _, _), a, b = two_entries
        other = await register_user(client, username=f"other-{uuid4().hex[:8]}")
        resp = await client.post(f"/v1/extensions/references/{a['id']}", json={"target_entry_id": b["id"], "rel": "supports"}, headers=auth_header(other["access_token"]))
        assert resp.status_code == 403

    async def test_create_unauthenticated(self, two_entries: tuple[AuthedFixture, dict, dict]) -> None:
        (client, _, _), a, b = two_entries
        resp = await client.post(f"/v1/extensions/references/{a['id']}", json={"target_entry_id": b["id"], "rel": "supports"})
        assert resp.status_code == 401


class TestOldEntryRefsRemoved:
    async def test_old_list_endpoint_gone(self, client: httpx.AsyncClient) -> None:
        resp = await client.get("/v1/entry-refs")
        assert resp.status_code == 404

    async def test_old_detail_endpoint_gone(self, client: httpx.AsyncClient) -> None:
        resp = await client.get(f"/v1/entry-refs/{uuid4()}")
        assert resp.status_code == 404
