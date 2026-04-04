# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for search visibility with the new visibility model.

Tests that private entries are excluded from search results for non-owners,
while owners see their private entries in search results.

Requires PostgreSQL (tsvector type) -- skipped on SQLite.
"""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import phiacta.extensions.metadata.models  # noqa: F401
import phiacta.extensions.tags.models  # noqa: F401
import phiacta.extensions.types.models  # noqa: F401

from tests.e2e.conftest import (
    auth_header,
    create_entry,
    register_user,
    set_entry_repo_status,
    set_entry_visibility,
)

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]

needs_pg = pytest.mark.skipif(
    "postgresql" not in os.environ.get("TEST_DATABASE_URL", ""),
    reason="Search visibility tests require PostgreSQL (TSVECTOR type)",
)

pytestmark = needs_pg


async def _ensure_search_version(
    session_factory: async_sessionmaker[AsyncSession],
) -> UUID:
    """Ensure a search_tsv version row exists and return its ID."""
    vid = uuid4()
    async with session_factory() as session:
        result = await session.execute(
            text("SELECT id FROM view_search_tsv_versions LIMIT 1")
        )
        row = result.first()
        if row:
            return row[0]  # type: ignore[return-value]
        await session.execute(
            text(
                "INSERT INTO view_search_tsv_versions (id, parameters) "
                "VALUES (:vid, '{}'::jsonb)"
            ),
            {"vid": str(vid)},
        )
        await session.execute(
            text(
                "INSERT INTO view_search_tsv_active (singleton, version_id) "
                "VALUES (TRUE, :vid) "
                "ON CONFLICT (singleton) DO UPDATE SET version_id = :vid"
            ),
            {"vid": str(vid)},
        )
        await session.commit()
    return vid


async def _insert_tsv(
    session_factory: async_sessionmaker[AsyncSession],
    entry_id: str,
    version_id: UUID,
    content: str,
) -> None:
    """Insert a tsvector row for an entry so it appears in search results."""
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO view_search_tsv (entry_id, version_id, tsv) "
                "VALUES (:eid, :vid, to_tsvector('english', :content))"
            ),
            {"eid": entry_id, "vid": str(version_id), "content": content},
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mount_routers(client: httpx.AsyncClient) -> None:
    from phiacta.extensions.metadata import router as mr
    from phiacta.extensions.tags import router as tr
    from phiacta.extensions.types import router as type_r
    from phiacta.tools.search.router import router as sr
    from phiacta.main import app as _app

    _app.include_router(mr, prefix="/v1/extensions/metadata", tags=["metadata"])
    _app.include_router(tr, prefix="/v1/extensions/tags", tags=["tags"])
    _app.include_router(type_r, prefix="/v1/extensions/types", tags=["types"])
    _app.include_router(sr, prefix="/v1/tools/search", tags=["search"])
    yield  # type: ignore[misc]
    _app.routes[:] = [
        r for r in _app.routes
        if not (
            hasattr(r, "path")
            and (
                r.path.startswith("/v1/extensions/metadata")
                or r.path.startswith("/v1/extensions/tags")
                or r.path.startswith("/v1/extensions/types")
                or r.path.startswith("/v1/tools/search")
            )
        )
    ]


@pytest.fixture
async def owner(client: httpx.AsyncClient) -> AuthedFixture:
    auth = await register_user(client, handle=f"svis-owner-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def other_user(client: httpx.AsyncClient) -> AuthedFixture:
    auth = await register_user(client, handle=f"svis-other-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def search_env(
    owner: AuthedFixture,
    other_user: AuthedFixture,
    e2e_session_factory: async_sessionmaker[AsyncSession],
) -> dict:
    """Create entries with mixed visibility for search testing."""
    client, _, owner_token = owner
    vid = await _ensure_search_version(e2e_session_factory)

    public_alpha = await create_entry(
        client, owner_token, title="Public Alpha Quantum",
        summary="Public quantum physics entry",
    )
    await set_entry_repo_status(e2e_session_factory, public_alpha["id"], "ready")
    await _insert_tsv(e2e_session_factory, public_alpha["id"], vid, "quantum physics alpha")

    public_beta = await create_entry(
        client, owner_token, title="Public Beta Quantum",
        summary="Public quantum math entry",
    )
    await set_entry_repo_status(e2e_session_factory, public_beta["id"], "ready")
    await _insert_tsv(e2e_session_factory, public_beta["id"], vid, "quantum math beta")

    private_gamma = await create_entry(
        client, owner_token, title="Private Gamma Quantum",
        summary="Private quantum entry",
    )
    await set_entry_repo_status(e2e_session_factory, private_gamma["id"], "ready")
    await set_entry_visibility(e2e_session_factory, private_gamma["id"], "private")
    await _insert_tsv(e2e_session_factory, private_gamma["id"], vid, "quantum private gamma")

    return {
        "public_alpha": public_alpha,
        "public_beta": public_beta,
        "private_gamma": private_gamma,
        "client": client,
        "owner_token": owner_token,
    }


def _ids(items: list[dict]) -> set[str]:
    return {item["entry_id"] for item in items}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSearchVisibilityExclusion:
    """Private entries silently excluded from search for non-owners."""

    async def test_private_excluded_from_search_for_non_owner(
        self, search_env: dict, other_user: AuthedFixture,
    ) -> None:
        client = search_env["client"]
        _, _, other_token = other_user
        resp = await client.get(
            "/v1/tools/search/",
            params={"q": "quantum"},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 200
        ids = _ids(resp.json()["items"])
        assert search_env["public_alpha"]["id"] in ids
        assert search_env["public_beta"]["id"] in ids
        assert search_env["private_gamma"]["id"] not in ids

    async def test_private_excluded_from_search_unauthenticated(
        self, search_env: dict,
    ) -> None:
        client = search_env["client"]
        resp = await client.get(
            "/v1/tools/search/",
            params={"q": "quantum"},
        )
        assert resp.status_code == 200
        ids = _ids(resp.json()["items"])
        assert search_env["public_alpha"]["id"] in ids
        assert search_env["public_beta"]["id"] in ids
        assert search_env["private_gamma"]["id"] not in ids

    async def test_owner_sees_own_private_entries_in_search(
        self, search_env: dict,
    ) -> None:
        client = search_env["client"]
        owner_token = search_env["owner_token"]
        resp = await client.get(
            "/v1/tools/search/",
            params={"q": "quantum"},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200
        ids = _ids(resp.json()["items"])
        assert search_env["public_alpha"]["id"] in ids
        assert search_env["public_beta"]["id"] in ids
        assert search_env["private_gamma"]["id"] in ids

    async def test_search_total_reflects_visibility(
        self, search_env: dict, other_user: AuthedFixture,
    ) -> None:
        client = search_env["client"]
        _, _, other_token = other_user
        resp_other = await client.get(
            "/v1/tools/search/",
            params={"q": "quantum"},
            headers=auth_header(other_token),
        )
        resp_owner = await client.get(
            "/v1/tools/search/",
            params={"q": "quantum"},
            headers=auth_header(search_env["owner_token"]),
        )
        assert len(resp_other.json()["items"]) < len(resp_owner.json()["items"])

    async def test_search_with_only_private_results_returns_empty(
        self, search_env: dict, other_user: AuthedFixture,
    ) -> None:
        client = search_env["client"]
        _, _, other_token = other_user
        resp = await client.get(
            "/v1/tools/search/",
            params={"q": "gamma"},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 200
        assert resp.json()["items"] == []
        assert resp.json()["has_more"] is False


class TestSearchTsvVisibility:
    """GET /v1/extensions/search_tsv/{entry_id} returns 403 for private entries."""

    async def test_search_tsv_direct_access_returns_403_for_non_owner(
        self, search_env: dict, other_user: AuthedFixture,
    ) -> None:
        client = search_env["client"]
        _, _, other_token = other_user
        private_id = search_env["private_gamma"]["id"]
        resp = await client.get(
            f"/v1/extensions/search_tsv/{private_id}",
            headers=auth_header(other_token),
        )
        assert resp.status_code == 403

    async def test_search_tsv_direct_access_returns_403_unauthenticated(
        self, search_env: dict,
    ) -> None:
        client = search_env["client"]
        private_id = search_env["private_gamma"]["id"]
        resp = await client.get(f"/v1/extensions/search_tsv/{private_id}")
        assert resp.status_code == 403

    async def test_owner_can_access_search_tsv_for_private_entry(
        self, search_env: dict,
    ) -> None:
        client = search_env["client"]
        owner_token = search_env["owner_token"]
        private_id = search_env["private_gamma"]["id"]
        resp = await client.get(
            f"/v1/extensions/search_tsv/{private_id}",
            headers=auth_header(owner_token),
        )
        assert resp.status_code != 403
