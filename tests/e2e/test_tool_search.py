# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for the search tool plugin (NEV-133).

Tests the full API path for:
- GET /v1/tools/search/?q=...  (full-text search over entries)

These tests exercise the real search pipeline: create entries, set content_cache,
compute tsvectors via search_tsv, then search via the search tool endpoint.

Requires PostgreSQL (plainto_tsquery, ts_rank, and GIN indexes are not available
in SQLite). Mark tests with `needs_pg` to skip when TEST_DATABASE_URL is not set
or is SQLite.
"""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from phiacta.core.models.entry import Entry
from phiacta.core.models.view_version import ViewVersion

# Import the search_tsv model at module level so Base.metadata.create_all
# includes the view_search_tsv table when the e2e_engine fixture runs.
import phiacta.views.search_tsv.models  # noqa: F401

from tests.e2e.conftest import (
    auth_header,
    create_entry,
    register_user,
    set_entry_repo_status,
    set_entry_status,
)

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]

# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

needs_pg = pytest.mark.skipif(
    "postgresql" not in os.environ.get("TEST_DATABASE_URL", ""),
    reason="search tool tests require PostgreSQL (plainto_tsquery, ts_rank)",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_active_version(
    session_factory: async_sessionmaker[AsyncSession],
) -> str:
    """Insert the active search_tsv ViewVersion row. Returns version_id as string."""
    async with session_factory() as session:
        vv = ViewVersion(
            view_type="search_tsv",
            version="v1",
            status="active",
            parameters={"language": "english"},
        )
        session.add(vv)
        await session.commit()
        return str(vv.id)


async def _set_content_cache(
    session_factory: async_sessionmaker[AsyncSession],
    entry_id: str,
    content: str | None,
) -> None:
    """Directly set content_cache on an entry."""
    async with session_factory() as session:
        result = await session.execute(
            select(Entry).where(Entry.id == UUID(entry_id))
        )
        entry = result.scalar_one()
        entry.content_cache = content
        await session.commit()


async def _compute_tsv(
    session_factory: async_sessionmaker[AsyncSession],
    entry_id: str,
    content: str,
    version_id: str,
) -> None:
    """Compute the tsvector for an entry using the search_tsv compute function."""
    from phiacta.views.search_tsv.compute import compute_search_tsv

    async with session_factory() as session:
        await compute_search_tsv(
            entry_id=UUID(entry_id),
            content_cache=content,
            version_id=UUID(version_id),
            db=session,
        )
        await session.commit()


async def _create_and_index_entry(
    client: httpx.AsyncClient,
    token: str,
    session_factory: async_sessionmaker[AsyncSession],
    version_id: str,
    *,
    title: str,
    content: str,
) -> dict:
    """Create an entry, set its content_cache, and compute its tsvector.

    Returns the entry response dict.
    """
    entry = await create_entry(client, token, title=title)
    await set_entry_repo_status(session_factory, entry["id"], "ready")
    await _set_content_cache(session_factory, entry["id"], content)
    await _compute_tsv(session_factory, entry["id"], content, version_id)
    return entry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mount_routers(client: httpx.AsyncClient) -> None:
    """Mount the search_tsv view router AND the search tool router on the test app.

    The E2E test client bypasses the lifespan hook where plugins are normally
    discovered, so we manually mount both routers at their correct prefixes.
    The search tool depends on search_tsv data, so both must be mounted.

    Depends on ``client`` to ensure dependency overrides are active.
    """
    from phiacta.views.search_tsv import router as search_tsv_router
    from phiacta.tools.search import router as search_router
    from phiacta.main import app as _app

    _app.include_router(
        search_tsv_router, prefix="/v1/views/search_tsv", tags=["search_tsv"]
    )
    _app.include_router(
        search_router, prefix="/v1/tools/search", tags=["search"]
    )
    yield  # type: ignore[misc]
    # Cleanup: remove plugin routes after test
    _app.routes[:] = [
        r
        for r in _app.routes
        if not (
            hasattr(r, "path")
            and (
                r.path.startswith("/v1/views/search_tsv")
                or r.path.startswith("/v1/tools/search")
            )
        )
    ]


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    """Register a user and return (client, user_data, token)."""
    uid = uuid4().hex[:8]
    auth = await register_user(client, handle=f"search-{uid}")
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def version_id(
    e2e_session_factory: async_sessionmaker[AsyncSession],
) -> str:
    """Seed the active search_tsv ViewVersion and return its id."""
    return await _seed_active_version(e2e_session_factory)


# ---------------------------------------------------------------------------
# GET /v1/tools/search/?q=... — Full-text search
# ---------------------------------------------------------------------------


@needs_pg
class TestTextSearchReturnsRankedResults:
    """Scenario: User searches for a term and receives ranked results.

    Create 3 entries with different content. Search for "quantum".
    Verify only the 2 relevant entries are returned, ranked by relevance,
    with correct response shape.
    """

    async def test_search_returns_matching_entries_ranked(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """GET /v1/tools/search/?q=quantum returns 2 matching entries ranked by relevance."""
        client, _, token = authed

        # Entry about quantum physics (high relevance for "quantum")
        e1 = await _create_and_index_entry(
            client, token, e2e_session_factory, version_id,
            title="Quantum Physics Overview",
            content=(
                "Quantum physics is the fundamental theory of nature at the "
                "smallest scales. Quantum mechanics describes the behavior of "
                "quantum particles and quantum fields in quantum systems."
            ),
        )

        # Entry about quantum computing (moderate relevance for "quantum")
        e2 = await _create_and_index_entry(
            client, token, e2e_session_factory, version_id,
            title="Quantum Computing Basics",
            content=(
                "Quantum computing leverages quantum mechanical phenomena "
                "to perform computation that classical computers cannot."
            ),
        )

        # Entry about biology (no relevance for "quantum")
        await _create_and_index_entry(
            client, token, e2e_session_factory, version_id,
            title="Biology 101",
            content=(
                "Biology is the scientific study of life and living organisms. "
                "Cells are the basic building blocks of all living things."
            ),
        )

        resp = await client.get("/v1/tools/search/", params={"q": "quantum"})
        assert resp.status_code == 200

        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

        # Results should be ranked: the entry with more "quantum" mentions first
        result_ids = [item["entry_id"] for item in data["items"]]
        assert e1["id"] in result_ids
        assert e2["id"] in result_ids

        # Verify ranking: first result should have higher rank than second
        assert data["items"][0]["rank"] >= data["items"][1]["rank"]

        # Verify each item has all required fields
        for item in data["items"]:
            assert "entry_id" in item
            assert "title" in item
            assert "rank" in item
            assert "layout_hint" in item
            assert isinstance(item["rank"], float)
            assert item["rank"] > 0

    async def test_search_does_not_return_non_matching_entries(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """Search for 'quantum' does not return the biology entry."""
        client, _, token = authed

        await _create_and_index_entry(
            client, token, e2e_session_factory, version_id,
            title="Biology 101",
            content="Biology is the study of life and living organisms.",
        )

        resp = await client.get("/v1/tools/search/", params={"q": "quantum"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert len(data["items"]) == 0


@needs_pg
class TestEmptyAndWhitespaceQueries:
    """Scenario: User submits empty or whitespace-only queries.

    These should be rejected with 422 validation errors.
    """

    async def test_empty_query_returns_422(
        self,
        client: httpx.AsyncClient,
        version_id: str,
    ) -> None:
        """GET /v1/tools/search/?q= returns 422 (empty string after strip)."""
        resp = await client.get("/v1/tools/search/", params={"q": ""})
        assert resp.status_code == 422

    async def test_missing_query_param_returns_422(
        self,
        client: httpx.AsyncClient,
        version_id: str,
    ) -> None:
        """GET /v1/tools/search/ without q param returns 422."""
        resp = await client.get("/v1/tools/search/")
        assert resp.status_code == 422

    async def test_whitespace_only_query_returns_422(
        self,
        client: httpx.AsyncClient,
        version_id: str,
    ) -> None:
        """GET /v1/tools/search/?q=%20 (single space) returns 422."""
        resp = await client.get("/v1/tools/search/", params={"q": " "})
        assert resp.status_code == 422

    async def test_multiple_spaces_query_returns_422(
        self,
        client: httpx.AsyncClient,
        version_id: str,
    ) -> None:
        """GET /v1/tools/search/?q=%20%20%20 (multiple spaces) returns 422."""
        resp = await client.get("/v1/tools/search/", params={"q": "   "})
        assert resp.status_code == 422

    async def test_tab_only_query_returns_422(
        self,
        client: httpx.AsyncClient,
        version_id: str,
    ) -> None:
        """GET /v1/tools/search/?q=\\t (tab) returns 422 after whitespace strip."""
        resp = await client.get("/v1/tools/search/", params={"q": "\t"})
        assert resp.status_code == 422


@needs_pg
class TestNoMatchesReturnsEmpty:
    """Scenario: User searches for a term with no matches.

    Should return 200 with empty items, total=0, has_more=false.
    """

    async def test_no_matches_returns_200_empty(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """Search for nonexistent term returns 200 with empty results."""
        client, _, token = authed

        await _create_and_index_entry(
            client, token, e2e_session_factory, version_id,
            title="Real Entry",
            content="This is a perfectly normal entry about programming.",
        )

        resp = await client.get(
            "/v1/tools/search/", params={"q": "xyznonexistent"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["has_more"] is False
        assert data["limit"] == 50  # default
        assert data["offset"] == 0  # default


@needs_pg
class TestPagination:
    """Scenario: User paginates through search results.

    Create 5 matching entries. Verify limit and offset work correctly,
    including has_more flag and total count consistency.
    """

    async def test_pagination_first_page(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """First page with limit=2 returns 2 items, total=5, has_more=true."""
        client, _, token = authed

        for i in range(5):
            await _create_and_index_entry(
                client, token, e2e_session_factory, version_id,
                title=f"Pagination Test Entry {i}",
                content=f"Machine learning algorithms for prediction task {i}.",
            )

        resp = await client.get(
            "/v1/tools/search/",
            params={"q": "machine learning", "limit": 2, "offset": 0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] == 5
        assert data["has_more"] is True
        assert data["limit"] == 2
        assert data["offset"] == 0

    async def test_pagination_last_page(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """Last page with limit=2, offset=4 returns 1 item, has_more=false."""
        client, _, token = authed

        for i in range(5):
            await _create_and_index_entry(
                client, token, e2e_session_factory, version_id,
                title=f"Page Test Entry {i}",
                content=f"Machine learning algorithm variant {i} with neural networks.",
            )

        resp = await client.get(
            "/v1/tools/search/",
            params={"q": "machine learning", "limit": 2, "offset": 4},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["total"] == 5
        assert data["has_more"] is False

    async def test_pagination_middle_page(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """Middle page with limit=2, offset=2 returns 2 items, has_more=true."""
        client, _, token = authed

        for i in range(5):
            await _create_and_index_entry(
                client, token, e2e_session_factory, version_id,
                title=f"Mid Page Entry {i}",
                content=f"Machine learning model number {i} for classification.",
            )

        resp = await client.get(
            "/v1/tools/search/",
            params={"q": "machine learning", "limit": 2, "offset": 2},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] == 5
        assert data["has_more"] is True

    async def test_total_is_consistent_across_pages(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """Total count is the same regardless of limit/offset."""
        client, _, token = authed

        for i in range(4):
            await _create_and_index_entry(
                client, token, e2e_session_factory, version_id,
                title=f"Consistency Entry {i}",
                content=f"Deep learning experiment {i} with transformers.",
            )

        resp1 = await client.get(
            "/v1/tools/search/",
            params={"q": "deep learning", "limit": 1, "offset": 0},
        )
        resp2 = await client.get(
            "/v1/tools/search/",
            params={"q": "deep learning", "limit": 1, "offset": 3},
        )
        assert resp1.json()["total"] == resp2.json()["total"] == 4


@needs_pg
class TestOffsetExceedsTotal:
    """Scenario: User requests an offset beyond the total result count.

    Should return 200 with empty items but the correct total.
    """

    async def test_offset_beyond_total_returns_empty_items(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """Search with offset=100 when only 3 results exist returns empty items."""
        client, _, token = authed

        for i in range(3):
            await _create_and_index_entry(
                client, token, e2e_session_factory, version_id,
                title=f"Offset Test {i}",
                content=f"Cryptography and encryption methods variant {i}.",
            )

        resp = await client.get(
            "/v1/tools/search/",
            params={"q": "cryptography", "limit": 50, "offset": 100},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 3
        assert data["has_more"] is False


@needs_pg
class TestNoActiveVersion:
    """Scenario: No active ViewVersion exists for search_tsv.

    The search tool should return 200 with empty results (not an error).
    """

    async def test_no_active_version_returns_empty_results(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """Search without any active version returns 200, empty items, total=0."""
        # No version_id fixture => no ViewVersion row exists
        resp = await client.get("/v1/tools/search/", params={"q": "anything"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["has_more"] is False


@needs_pg
class TestArchivedEntriesExcluded:
    """Scenario: Archived entries should not appear in search results.

    Create an entry, compute its tsvector, then archive it. Search should
    NOT return it.
    """

    async def test_archived_entry_excluded_from_results(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """Search does not return entries with status='archived'."""
        client, _, token = authed

        # Create and index an entry
        entry = await _create_and_index_entry(
            client, token, e2e_session_factory, version_id,
            title="Archived Entry",
            content="This entry discusses neural network architectures in detail.",
        )

        # Verify it appears in search before archiving
        resp = await client.get(
            "/v1/tools/search/", params={"q": "neural network"}
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

        # Archive the entry
        await set_entry_status(e2e_session_factory, entry["id"], "archived")

        # Search again — should NOT appear
        resp = await client.get(
            "/v1/tools/search/", params={"q": "neural network"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    async def test_mix_of_active_and_archived_entries(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """When one entry is active and one is archived, only active appears."""
        client, _, token = authed

        active_entry = await _create_and_index_entry(
            client, token, e2e_session_factory, version_id,
            title="Active Robotics",
            content="Robotics engineering and robot design principles.",
        )
        archived_entry = await _create_and_index_entry(
            client, token, e2e_session_factory, version_id,
            title="Archived Robotics",
            content="Advanced robotics and autonomous robot systems.",
        )

        # Archive the second entry
        await set_entry_status(
            e2e_session_factory, archived_entry["id"], "archived"
        )

        resp = await client.get(
            "/v1/tools/search/", params={"q": "robotics"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["entry_id"] == active_entry["id"]


@needs_pg
class TestResponseShapeVerification:
    """Scenario: Verify the exact response shape from the search endpoint.

    All fields must be present with correct types and values.
    """

    async def test_response_has_all_top_level_fields(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """Response contains items, total, limit, offset, has_more, version_id."""
        client, _, token = authed

        await _create_and_index_entry(
            client, token, e2e_session_factory, version_id,
            title="Shape Test Entry",
            content="Thermodynamics and entropy in closed systems.",
        )

        resp = await client.get(
            "/v1/tools/search/", params={"q": "thermodynamics"}
        )
        assert resp.status_code == 200
        data = resp.json()

        # All required top-level fields
        required_top_level = {"items", "total", "limit", "offset", "has_more", "version_id"}
        assert required_top_level.issubset(set(data.keys())), (
            f"Missing fields: {required_top_level - set(data.keys())}"
        )

        # Type assertions for top-level fields
        assert isinstance(data["items"], list)
        assert isinstance(data["total"], int)
        assert isinstance(data["limit"], int)
        assert isinstance(data["offset"], int)
        assert isinstance(data["has_more"], bool)
        assert isinstance(data["version_id"], str)

    async def test_response_item_has_all_required_fields(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """Each item has entry_id, title, summary, layout_hint, rank."""
        client, _, token = authed

        await _create_and_index_entry(
            client, token, e2e_session_factory, version_id,
            title="Item Shape Test",
            content="Photosynthesis converts sunlight into chemical energy in plants.",
        )

        resp = await client.get(
            "/v1/tools/search/", params={"q": "photosynthesis"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1

        item = data["items"][0]
        required_item_fields = {"entry_id", "title", "summary", "layout_hint", "rank"}
        assert required_item_fields.issubset(set(item.keys())), (
            f"Missing item fields: {required_item_fields - set(item.keys())}"
        )

        # Type assertions for item fields
        assert isinstance(item["entry_id"], str)
        assert isinstance(item["title"], str)
        # summary can be None or str
        assert item["summary"] is None or isinstance(item["summary"], str)
        # layout_hint can be None or str
        assert item["layout_hint"] is None or isinstance(item["layout_hint"], str)
        assert isinstance(item["rank"], (int, float))
        assert item["rank"] > 0

    async def test_item_entry_id_matches_created_entry(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """The entry_id in search results matches the created entry."""
        client, _, token = authed

        entry = await _create_and_index_entry(
            client, token, e2e_session_factory, version_id,
            title="ID Match Test",
            content="Astrophysics studies celestial objects and phenomena.",
        )

        resp = await client.get(
            "/v1/tools/search/", params={"q": "astrophysics"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["entry_id"] == entry["id"]
        assert data["items"][0]["title"] == "ID Match Test"


@needs_pg
class TestVersionIdInResponse:
    """Scenario: The response includes the version_id of the active ViewVersion.

    This allows clients to know which version of the search index was used.
    """

    async def test_version_id_matches_active_version(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """The version_id in the response matches the seeded active version."""
        client, _, token = authed

        await _create_and_index_entry(
            client, token, e2e_session_factory, version_id,
            title="Version ID Test",
            content="Organic chemistry studies carbon-based compounds.",
        )

        resp = await client.get(
            "/v1/tools/search/", params={"q": "organic chemistry"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["version_id"] == version_id

    async def test_version_id_in_empty_results_when_version_exists(
        self,
        client: httpx.AsyncClient,
        version_id: str,
    ) -> None:
        """Even with no results, version_id is present if a version exists."""
        resp = await client.get(
            "/v1/tools/search/", params={"q": "nonexistent"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["version_id"] == version_id


@needs_pg
class TestSpecialCharactersInQuery:
    """Scenario: User searches with special characters in the query.

    plainto_tsquery should handle special characters gracefully without
    SQL injection or parsing errors.
    """

    async def test_special_characters_do_not_cause_error(
        self,
        client: httpx.AsyncClient,
        version_id: str,
    ) -> None:
        """Search with special characters returns 200 (empty is fine, no 500)."""
        resp = await client.get(
            "/v1/tools/search/", params={"q": "Einstein's E=mc^2"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["items"], list)
        assert isinstance(data["total"], int)

    async def test_query_with_sql_injection_attempt(
        self,
        client: httpx.AsyncClient,
        version_id: str,
    ) -> None:
        """SQL injection attempts are handled safely by plainto_tsquery."""
        resp = await client.get(
            "/v1/tools/search/",
            params={"q": "'; DROP TABLE entries; --"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["items"], list)

    async def test_query_with_tsquery_operators(
        self,
        client: httpx.AsyncClient,
        version_id: str,
    ) -> None:
        """plainto_tsquery treats operators as plain text, not tsquery syntax."""
        resp = await client.get(
            "/v1/tools/search/", params={"q": "quantum & physics | biology"}
        )
        assert resp.status_code == 200

    async def test_unicode_query(
        self,
        client: httpx.AsyncClient,
        version_id: str,
    ) -> None:
        """Unicode characters in the query do not cause errors."""
        resp = await client.get(
            "/v1/tools/search/", params={"q": "Schrodinger"}
        )
        assert resp.status_code == 200


@needs_pg
class TestStopWordOnlyQuery:
    """Scenario: User searches with only stop words.

    plainto_tsquery eliminates stop words in English configuration,
    resulting in an empty tsquery that matches nothing. Should return 200
    with empty results.
    """

    async def test_stop_words_only_returns_empty_results(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """Search for 'the is a' (all stop words) returns 200, empty items."""
        client, _, token = authed

        # Create an entry so the table is not empty
        await _create_and_index_entry(
            client, token, e2e_session_factory, version_id,
            title="Stop Words Test",
            content="This entry has real content about algorithms and data structures.",
        )

        resp = await client.get(
            "/v1/tools/search/", params={"q": "the is a"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0


@needs_pg
class TestLimitValidation:
    """Scenario: User provides invalid limit values.

    limit must be between 1 and 200. Values outside this range should return 422.
    """

    async def test_limit_zero_returns_422(
        self,
        client: httpx.AsyncClient,
        version_id: str,
    ) -> None:
        """limit=0 is invalid (minimum is 1)."""
        resp = await client.get(
            "/v1/tools/search/", params={"q": "test", "limit": 0}
        )
        assert resp.status_code == 422

    async def test_limit_201_returns_422(
        self,
        client: httpx.AsyncClient,
        version_id: str,
    ) -> None:
        """limit=201 is invalid (maximum is 200)."""
        resp = await client.get(
            "/v1/tools/search/", params={"q": "test", "limit": 201}
        )
        assert resp.status_code == 422

    async def test_limit_negative_returns_422(
        self,
        client: httpx.AsyncClient,
        version_id: str,
    ) -> None:
        """limit=-1 is invalid."""
        resp = await client.get(
            "/v1/tools/search/", params={"q": "test", "limit": -1}
        )
        assert resp.status_code == 422

    async def test_limit_1_is_valid(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """limit=1 is valid and returns at most 1 item."""
        client, _, token = authed

        await _create_and_index_entry(
            client, token, e2e_session_factory, version_id,
            title="Limit One Test",
            content="Geology studies the solid Earth and its minerals.",
        )

        resp = await client.get(
            "/v1/tools/search/", params={"q": "geology", "limit": 1}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) <= 1
        assert data["limit"] == 1

    async def test_limit_200_is_valid(
        self,
        client: httpx.AsyncClient,
        version_id: str,
    ) -> None:
        """limit=200 is valid (boundary value)."""
        resp = await client.get(
            "/v1/tools/search/", params={"q": "test", "limit": 200}
        )
        assert resp.status_code == 200
        assert resp.json()["limit"] == 200

    async def test_negative_offset_returns_422(
        self,
        client: httpx.AsyncClient,
        version_id: str,
    ) -> None:
        """offset=-1 is invalid."""
        resp = await client.get(
            "/v1/tools/search/", params={"q": "test", "offset": -1}
        )
        assert resp.status_code == 422


@needs_pg
class TestSearchWhenTableEmpty:
    """Scenario: Active version exists but no tsvectors have been computed.

    Should return 200 with empty items, not an error.
    """

    async def test_empty_table_returns_200_empty(
        self,
        client: httpx.AsyncClient,
        version_id: str,
    ) -> None:
        """Search when view_search_tsv table has no rows returns 200, empty items."""
        resp = await client.get(
            "/v1/tools/search/", params={"q": "anything"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["has_more"] is False
        assert data["version_id"] == version_id


@needs_pg
class TestDefaultPaginationValues:
    """Scenario: User does not specify limit or offset.

    Default limit should be 50, default offset should be 0.
    """

    async def test_default_limit_is_50(
        self,
        client: httpx.AsyncClient,
        version_id: str,
    ) -> None:
        """Without explicit limit, the default is 50."""
        resp = await client.get(
            "/v1/tools/search/", params={"q": "test"}
        )
        assert resp.status_code == 200
        assert resp.json()["limit"] == 50

    async def test_default_offset_is_0(
        self,
        client: httpx.AsyncClient,
        version_id: str,
    ) -> None:
        """Without explicit offset, the default is 0."""
        resp = await client.get(
            "/v1/tools/search/", params={"q": "test"}
        )
        assert resp.status_code == 200
        assert resp.json()["offset"] == 0


@needs_pg
class TestSearchWithSummaryAndLayoutHint:
    """Scenario: Search results include the entry's summary and layout_hint.

    These fields come from the entries table, not the tsvector table.
    """

    async def test_summary_and_layout_hint_populated_in_results(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """Items in search results include the entry's summary and layout_hint."""
        client, _, token = authed

        # Create an entry — check that summary is returned from the entries table
        entry = await _create_and_index_entry(
            client, token, e2e_session_factory, version_id,
            title="Summary Test",
            content="Plate tectonics explains the movement of Earth's lithospheric plates.",
        )

        # Set summary directly on the entry
        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry["id"]))
            )
            e = result.scalar_one()
            e.summary = "A brief overview of plate tectonics."
            e.layout_hint = "article"
            await session.commit()

        resp = await client.get(
            "/v1/tools/search/", params={"q": "plate tectonics"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1

        item = data["items"][0]
        assert item["summary"] == "A brief overview of plate tectonics."
        assert item["layout_hint"] == "article"
        assert item["title"] == "Summary Test"
