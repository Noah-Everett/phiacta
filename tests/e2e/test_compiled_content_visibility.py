# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for compiled content visibility — ensures GET
/v1/extensions/compiled_content/{entry_id} respects entry visibility.

Would have caught PHI-247.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from phiacta.extensions.compiled_content.models import CompiledOutput  # noqa: F401 — register table
from tests.e2e.conftest import (
    auth_header,
    create_entry,
    register_user,
    set_entry_repo_status,
    set_entry_visibility,
)


@pytest.fixture(autouse=True)
def _mount_compiled_content_router(client: httpx.AsyncClient) -> None:
    from phiacta.extensions.compiled_content.router import router as ccr
    from phiacta.main import app as _app

    _app.include_router(ccr, prefix="/v1/extensions/compiled_content", tags=["compiled_content"])
    yield  # type: ignore[misc]
    _app.routes[:] = [
        r for r in _app.routes
        if not (hasattr(r, "path") and r.path.startswith("/v1/extensions/compiled_content"))
    ]


async def insert_compiled_output(
    session_factory: async_sessionmaker[AsyncSession],
    entry_id: str,
) -> None:
    """Insert a fake compiled PDF directly via the ORM model."""
    async with session_factory() as session:
        row = CompiledOutput(
            id=uuid4(),
            entity_id=UUID(entry_id),
            format="pdf",
            data=b"%PDF-1.4 fake content",
            source_sha="abc123" + "0" * 34,
            file_size=21,
            compiled_at=datetime.now(UTC),
            accessed_at=datetime.now(UTC),
        )
        session.add(row)
        await session.commit()


class TestCompiledContentVisibility:
    async def test_private_entry_unauthenticated_returns_403(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        auth = await register_user(client, username=f"cc-owner-{uuid4().hex[:8]}")
        token = auth["access_token"]
        entry = await create_entry(client, token, title="Private CC")
        await set_entry_repo_status(e2e_session_factory, entry["id"], "ready")
        await set_entry_visibility(e2e_session_factory, entry["id"], "private")
        await insert_compiled_output(e2e_session_factory, entry["id"])

        resp = await client.get(f"/v1/extensions/compiled_content/{entry['id']}")
        assert resp.status_code == 403
        assert "do not have access" in resp.json()["detail"]

    async def test_private_entry_other_user_returns_403(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        owner = await register_user(client, username=f"cc-own-{uuid4().hex[:8]}")
        other = await register_user(client, username=f"cc-oth-{uuid4().hex[:8]}")
        entry = await create_entry(client, owner["access_token"], title="Private CC 2")
        await set_entry_repo_status(e2e_session_factory, entry["id"], "ready")
        await set_entry_visibility(e2e_session_factory, entry["id"], "private")
        await insert_compiled_output(e2e_session_factory, entry["id"])

        resp = await client.get(
            f"/v1/extensions/compiled_content/{entry['id']}",
            headers=auth_header(other["access_token"]),
        )
        assert resp.status_code == 403
        assert "do not have access" in resp.json()["detail"]

    async def test_private_entry_owner_returns_200(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        owner = await register_user(client, username=f"cc-own2-{uuid4().hex[:8]}")
        entry = await create_entry(client, owner["access_token"], title="Private CC 3")
        await set_entry_repo_status(e2e_session_factory, entry["id"], "ready")
        await set_entry_visibility(e2e_session_factory, entry["id"], "private")
        await insert_compiled_output(e2e_session_factory, entry["id"])

        resp = await client.get(
            f"/v1/extensions/compiled_content/{entry['id']}",
            headers=auth_header(owner["access_token"]),
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"

    async def test_public_entry_unauthenticated_returns_200(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        owner = await register_user(client, username=f"cc-pub-{uuid4().hex[:8]}")
        entry = await create_entry(client, owner["access_token"], title="Public CC")
        await set_entry_repo_status(e2e_session_factory, entry["id"], "ready")
        await set_entry_visibility(e2e_session_factory, entry["id"], "public")
        await insert_compiled_output(e2e_session_factory, entry["id"])

        resp = await client.get(f"/v1/extensions/compiled_content/{entry['id']}")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"

    async def test_public_entry_no_compiled_output_returns_404(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        owner = await register_user(client, username=f"cc-no-{uuid4().hex[:8]}")
        entry = await create_entry(client, owner["access_token"], title="No PDF")
        await set_entry_repo_status(e2e_session_factory, entry["id"], "ready")
        await set_entry_visibility(e2e_session_factory, entry["id"], "public")
        # Deliberately do NOT insert compiled output

        resp = await client.get(f"/v1/extensions/compiled_content/{entry['id']}")
        assert resp.status_code == 404
