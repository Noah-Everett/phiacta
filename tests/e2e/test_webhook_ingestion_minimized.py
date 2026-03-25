# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for webhook ingestion after entry minimization."""

from __future__ import annotations

import hashlib
import hmac
import json
from uuid import UUID, uuid4

import httpx
import pytest
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from phiacta.core.models.entry import Entry
import phiacta.extensions.metadata.models  # noqa: F401

from tests.e2e.conftest import (
    TEST_WEBHOOK_SECRET, FakeGitService, auth_header, create_entry, register_user, set_entry_repo_status,
)

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
    auth = await register_user(client, handle=f"webhook-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


def _make_entry_yaml(entry_id: UUID, author_id: UUID) -> bytes:
    return yaml.dump({"entry_id": f"ent_{entry_id}", "schema_version": 1, "author": {"id": f"usr_{author_id}", "name": "test"}, "created_at": "2026-01-01T00:00:00"}, default_flow_style=False, sort_keys=False).encode()


async def _send_push(client, payload):
    body = json.dumps(payload).encode()
    sig = hmac.new(TEST_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return await client.post("/webhooks/forgejo", content=body, headers={"Content-Type": "application/json", "X-Forgejo-Signature": sig, "X-Forgejo-Event": "push"})


async def _setup(client, token, user_id, fake_git, e2e_sf, *, content=None, content_filename=".phiacta/content.md"):
    entry = await create_entry(client, token, title="Webhook Test")
    eid = UUID(entry["id"])
    await set_entry_repo_status(e2e_sf, entry["id"], "ready")
    async with e2e_sf() as session:
        result = await session.execute(select(Entry).where(Entry.id == eid))
        e = result.scalar_one()
        e.repo_name = str(eid)
        await session.commit()
    fake_git.files[(eid, ".phiacta/entry.yaml")] = _make_entry_yaml(eid, UUID(user_id))
    if content is not None:
        fake_git.files[(eid, content_filename)] = content
    return entry


class TestContentIngestion:
    async def test_ingestion_reads_content_md(self, authed: AuthedFixture, fake_git: FakeGitService, e2e_session_factory: async_sessionmaker[AsyncSession]) -> None:
        client, user, token = authed
        entry = await _setup(client, token, user["id"], fake_git, e2e_session_factory, content=b"# Quantum\n\nPhysics.")
        resp = await _send_push(client, {"ref": "refs/heads/main", "before": "0"*40, "after": "a"*40, "repository": {"name": str(entry["id"]), "full_name": f"p/{entry['id']}", "id": 42}, "commits": [{"id": "a"*40, "message": "u"}], "sender": {"login": "t"}})
        assert resp.status_code == 200

    async def test_ingestion_no_content_file_succeeds(self, authed: AuthedFixture, fake_git: FakeGitService, e2e_session_factory: async_sessionmaker[AsyncSession]) -> None:
        client, user, token = authed
        entry = await _setup(client, token, user["id"], fake_git, e2e_session_factory)
        resp = await _send_push(client, {"ref": "refs/heads/main", "before": "0"*40, "after": "c"*40, "repository": {"name": str(entry["id"]), "full_name": f"p/{entry['id']}", "id": 42}, "commits": [{"id": "c"*40, "message": "u"}], "sender": {"login": "t"}})
        assert resp.status_code == 200
