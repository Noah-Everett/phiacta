# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for search endpoint filtering.

Tests the dynamic filter mechanism: visibility, entry_type, tags, combined
filters, and unknown params. These tests create entries with known
types/tags and insert tsvector rows directly so the search endpoint
returns them.

Requires PostgreSQL (tsvector type) — skipped on SQLite.
"""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Ensure all extension tables are created.
import phiacta.extensions.metadata.models  # noqa: F401
import phiacta.extensions.tags.models  # noqa: F401
import phiacta.extensions.types.models  # noqa: F401
import phiacta.extensions.search_tsv.models  # noqa: F401

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
    reason="Search filter tests require PostgreSQL (TSVECTOR type)",
)

pytestmark = needs_pg


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
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    auth = await register_user(client, handle=f"sf-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


async def _ensure_search_version(
    session_factory: async_sessionmaker[AsyncSession],
) -> UUID:
    """Ensure a search_tsv version row exists and return its ID."""
    vid = uuid4()
    async with session_factory() as session:
        # Check if any version exists
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
        # Set as active
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


async def _set_tags(
    client: httpx.AsyncClient,
    token: str,
    entry_id: str,
    tags: list[str],
) -> None:
    resp = await client.put(
        f"/v1/extensions/tags/{entry_id}",
        json={"tags": tags},
        headers=auth_header(token),
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Test helpers — create a seeded search environment
# ---------------------------------------------------------------------------


@pytest.fixture
async def search_env(
    authed: AuthedFixture,
    e2e_session_factory: async_sessionmaker[AsyncSession],
) -> dict:
    """Create entries with known types, tags, and tsvector content.

    Returns a dict with entry dicts keyed by role:
      - "alpha": type=empirical, tags=[physics, quantum], content has "quantum"
      - "beta":  type=theorem,   tags=[math],             content has "quantum"
      - "gamma": type=empirical, tags=[math, physics],    content has "gamma"
      - "private": type=empirical, visibility=private,    content has "quantum"
    """
    client, user, token = authed
    vid = await _ensure_search_version(e2e_session_factory)

    alpha = await create_entry(
        client, token, title="Alpha Quantum", entry_type="empirical",
        summary="Alpha quantum physics entry",
    )
    await set_entry_repo_status(e2e_session_factory, alpha["id"], "ready")
    await _set_tags(client, token, alpha["id"], ["physics", "quantum"])
    await _insert_tsv(e2e_session_factory, alpha["id"], vid, "quantum physics alpha")

    beta = await create_entry(
        client, token, title="Beta Quantum", entry_type="theorem",
        summary="Beta quantum math theorem",
    )
    await set_entry_repo_status(e2e_session_factory, beta["id"], "ready")
    await _set_tags(client, token, beta["id"], ["math"])
    await _insert_tsv(e2e_session_factory, beta["id"], vid, "quantum math beta")

    gamma = await create_entry(
        client, token, title="Gamma Entry", entry_type="empirical",
        summary="Gamma math physics entry",
    )
    await set_entry_repo_status(e2e_session_factory, gamma["id"], "ready")
    await _set_tags(client, token, gamma["id"], ["math", "physics"])
    await _insert_tsv(e2e_session_factory, gamma["id"], vid, "gamma math physics")

    private = await create_entry(
        client, token, title="Private Quantum", entry_type="empirical",
        summary="Private quantum entry",
    )
    await set_entry_repo_status(e2e_session_factory, private["id"], "ready")
    await set_entry_visibility(e2e_session_factory, private["id"], "private")
    await _insert_tsv(e2e_session_factory, private["id"], vid, "quantum private")

    return {
        "alpha": alpha,
        "beta": beta,
        "gamma": gamma,
        "private": private,
        "client": client,
        "token": token,
    }


def _ids(items: list[dict]) -> set[str]:
    return {item["entry_id"] for item in items}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSearchVisibilityFilter:
    async def test_default_visibility_is_public(self, search_env: dict) -> None:
        """Default search (no visibility param) returns only public entries."""
        client = search_env["client"]
        resp = await client.get("/v1/tools/search/", params={"q": "quantum"})
        assert resp.status_code == 200
        ids = _ids(resp.json()["items"])
        assert search_env["alpha"]["id"] in ids
        assert search_env["beta"]["id"] in ids
        assert search_env["private"]["id"] not in ids

    async def test_visibility_private_owner(self, search_env: dict) -> None:
        """visibility=private returns owner's private entries."""
        client, token = search_env["client"], search_env["token"]
        resp = await client.get(
            "/v1/tools/search/",
            params={"q": "quantum", "visibility": "private"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        ids = _ids(resp.json()["items"])
        assert search_env["private"]["id"] in ids
        assert search_env["alpha"]["id"] not in ids
        assert search_env["beta"]["id"] not in ids

    async def test_visibility_private_unauthenticated(self, search_env: dict) -> None:
        """visibility=private without auth returns no private entries."""
        client = search_env["client"]
        resp = await client.get(
            "/v1/tools/search/", params={"q": "quantum", "visibility": "private"}
        )
        assert resp.status_code == 200
        assert search_env["private"]["id"] not in _ids(resp.json()["items"])

    async def test_visibility_all_owner(self, search_env: dict) -> None:
        """visibility=all returns both public and owner's private entries."""
        client, token = search_env["client"], search_env["token"]
        resp = await client.get(
            "/v1/tools/search/",
            params={"q": "quantum", "visibility": "all"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        ids = _ids(resp.json()["items"])
        assert search_env["alpha"]["id"] in ids
        assert search_env["private"]["id"] in ids

    async def test_visibility_all_unauthenticated(self, search_env: dict) -> None:
        """visibility=all without auth hides private entries."""
        client = search_env["client"]
        resp = await client.get(
            "/v1/tools/search/", params={"q": "quantum", "visibility": "all"}
        )
        assert resp.status_code == 200
        ids = _ids(resp.json()["items"])
        assert search_env["alpha"]["id"] in ids
        assert search_env["private"]["id"] not in ids


class TestSearchEntryTypeFilter:
    async def test_filter_single_type(self, search_env: dict) -> None:
        client = search_env["client"]
        resp = await client.get(
            "/v1/tools/search/", params={"q": "quantum", "entry_type": "empirical"}
        )
        assert resp.status_code == 200
        ids = _ids(resp.json()["items"])
        assert search_env["alpha"]["id"] in ids
        assert search_env["beta"]["id"] not in ids  # theorem, not empirical

    async def test_filter_multiple_types(self, search_env: dict) -> None:
        client = search_env["client"]
        resp = await client.get(
            "/v1/tools/search/",
            params={"q": "quantum", "entry_type": "empirical,theorem"},
        )
        assert resp.status_code == 200
        ids = _ids(resp.json()["items"])
        assert search_env["alpha"]["id"] in ids
        assert search_env["beta"]["id"] in ids

    async def test_filter_nonexistent_type_returns_empty(self, search_env: dict) -> None:
        client = search_env["client"]
        resp = await client.get(
            "/v1/tools/search/", params={"q": "quantum", "entry_type": "nonexistent"}
        )
        assert resp.status_code == 200
        assert resp.json()["items"] == []
        assert resp.json()["total"] == 0


class TestSearchTagsFilter:
    async def test_tags_or_mode_default(self, search_env: dict) -> None:
        """tags=physics returns entries with the physics tag (OR is default)."""
        client = search_env["client"]
        resp = await client.get(
            "/v1/tools/search/", params={"q": "quantum", "tags": "physics"}
        )
        assert resp.status_code == 200
        ids = _ids(resp.json()["items"])
        assert search_env["alpha"]["id"] in ids  # has physics
        assert search_env["beta"]["id"] not in ids  # has math only

    async def test_tags_or_mode_multiple(self, search_env: dict) -> None:
        """tags=physics,math with default OR returns entries with either tag."""
        client = search_env["client"]
        resp = await client.get(
            "/v1/tools/search/", params={"q": "quantum", "tags": "physics,math"}
        )
        assert resp.status_code == 200
        ids = _ids(resp.json()["items"])
        assert search_env["alpha"]["id"] in ids  # has physics
        assert search_env["beta"]["id"] in ids  # has math

    async def test_tags_and_mode(self, search_env: dict) -> None:
        """tags=math,physics;mode=and returns only entries with BOTH tags."""
        client = search_env["client"]
        # Search for "gamma" or broader — gamma has both math and physics
        resp = await client.get(
            "/v1/tools/search/",
            params={"q": "gamma OR quantum OR math OR physics", "tags": "math,physics;mode=and"},
        )
        assert resp.status_code == 200
        ids = _ids(resp.json()["items"])
        # alpha has physics+quantum (not math) — should NOT match AND(math,physics)
        assert search_env["alpha"]["id"] not in ids
        # beta has math only — should NOT match
        assert search_env["beta"]["id"] not in ids
        # gamma has math+physics — SHOULD match
        assert search_env["gamma"]["id"] in ids

    async def test_tags_nonexistent_returns_empty(self, search_env: dict) -> None:
        client = search_env["client"]
        resp = await client.get(
            "/v1/tools/search/",
            params={"q": "quantum", "tags": "nonexistent-tag-xyz"},
        )
        assert resp.status_code == 200
        assert resp.json()["items"] == []
        assert resp.json()["total"] == 0


class TestSearchCombinedFilters:
    async def test_visibility_and_entry_type(self, search_env: dict) -> None:
        """Combine visibility=all with entry_type=empirical (owner sees private)."""
        client, token = search_env["client"], search_env["token"]
        resp = await client.get(
            "/v1/tools/search/",
            params={"q": "quantum", "visibility": "all", "entry_type": "empirical"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        ids = _ids(resp.json()["items"])
        assert search_env["alpha"]["id"] in ids  # public empirical
        assert search_env["private"]["id"] in ids  # private empirical
        assert search_env["beta"]["id"] not in ids  # theorem

    async def test_entry_type_and_tags(self, search_env: dict) -> None:
        """Combine entry_type=empirical with tags=physics."""
        client = search_env["client"]
        resp = await client.get(
            "/v1/tools/search/",
            params={
                "q": "quantum OR gamma OR physics",
                "entry_type": "empirical",
                "tags": "physics",
            },
        )
        assert resp.status_code == 200
        ids = _ids(resp.json()["items"])
        assert search_env["alpha"]["id"] in ids  # empirical + physics
        assert search_env["gamma"]["id"] in ids  # empirical + physics
        assert search_env["beta"]["id"] not in ids  # theorem

    async def test_all_three_filters(self, search_env: dict) -> None:
        """Combine visibility + entry_type + tags."""
        client = search_env["client"]
        resp = await client.get(
            "/v1/tools/search/",
            params={
                "q": "quantum OR gamma OR math OR physics",
                "visibility": "public",
                "entry_type": "empirical",
                "tags": "math,physics;mode=and",
            },
        )
        assert resp.status_code == 200
        ids = _ids(resp.json()["items"])
        # Only gamma is active + empirical + has both math and physics
        assert search_env["gamma"]["id"] in ids
        assert search_env["alpha"]["id"] not in ids  # missing math tag
        assert search_env["beta"]["id"] not in ids  # theorem


class TestSearchUnknownParams:
    async def test_unknown_filter_param_ignored(self, search_env: dict) -> None:
        """Unknown query params should be silently ignored."""
        client = search_env["client"]
        resp = await client.get(
            "/v1/tools/search/",
            params={"q": "quantum", "bogus_filter": "whatever"},
        )
        assert resp.status_code == 200
        # Should return normal results, not error
        assert "items" in resp.json()


class TestSearchPagination:
    async def test_total_reflects_filters(self, search_env: dict) -> None:
        """Total count should reflect applied filters, not all matches."""
        client = search_env["client"]
        # Unfiltered
        resp_all = await client.get(
            "/v1/tools/search/", params={"q": "quantum"}
        )
        # Filtered by type
        resp_filtered = await client.get(
            "/v1/tools/search/", params={"q": "quantum", "entry_type": "theorem"}
        )
        assert resp_all.status_code == 200
        assert resp_filtered.status_code == 200
        # Filtered total should be less than or equal to unfiltered
        assert resp_filtered.json()["total"] <= resp_all.json()["total"]
        # And specifically, only beta is a theorem that matches "quantum"
        assert resp_filtered.json()["total"] == 1
