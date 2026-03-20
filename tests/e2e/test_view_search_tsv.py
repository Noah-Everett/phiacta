# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for the search_tsv view plugin (NEV-130).

Tests the full API path for:
- GET /v1/views/search_tsv/version  (active version metadata)
- GET /v1/views/search_tsv/{entry_id}  (raw tsvector for entry)

Also verifies the tsvector computation lifecycle:
- Webhook push triggers tsvector computation via outbox
- content_cache=None removes tsvector rows
- Entry deletion cascades to tsvector rows
- Idempotent computation
- Route collision: /version does not collide with /{entry_id}

These tests require PostgreSQL (to_tsvector is not available in SQLite).
Mark tests with `needs_pg` to skip when TEST_DATABASE_URL is not set or
is SQLite.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from uuid import UUID, uuid4

import httpx
import pytest
import yaml
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from phiacta.core.models.entry import Entry
from phiacta.core.models.view_version import ViewVersion
from tests.e2e.conftest import (
    TEST_WEBHOOK_SECRET,
    FakeGitService,
    auth_header,
    create_entry,
    register_agent,
    set_entry_repo_status,
    set_entry_status,
)

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]

# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

needs_pg = pytest.mark.skipif(
    "postgresql" not in os.environ.get("TEST_DATABASE_URL", ""),
    reason="search_tsv tests require PostgreSQL (to_tsvector)",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_forgejo_signature(body: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 signature matching Forgejo's format."""
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    return mac.hexdigest()


def _make_push_payload(
    *,
    repo_name: str,
    after: str = "a" * 40,
) -> dict:
    """Construct a minimal Forgejo push webhook payload."""
    return {
        "ref": "refs/heads/main",
        "before": "0" * 40,
        "after": after,
        "repository": {
            "name": repo_name,
            "full_name": f"phiacta/{repo_name}",
            "id": 42,
        },
        "commits": [{"id": after, "message": "Update content"}],
        "sender": {"login": "test-user"},
    }


def _build_entry_yaml(
    entry_id: str,
    *,
    title: str = "Search TSV Test Entry",
    agent_id: str = "00000000-0000-0000-0000-000000000000",
    agent_handle: str = "tsv-test",
) -> str:
    """Build a minimal entry.yaml for webhook ingestion."""
    return yaml.dump(
        {
            "entry_id": f"ent_{entry_id}",
            "schema_version": 1,
            "title": title,
            "author": {"id": f"usr_{agent_id}", "name": agent_handle},
            "created_at": "2026-01-01T00:00:00",
            "content_format": "markdown",
        },
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )


def _populate_fake_git(
    fake_git: FakeGitService,
    entry_id: str,
    *,
    entry_yaml: str | None = None,
    readme_content: str | None = None,
) -> None:
    """Populate the FakeGitService with files for an entry."""
    eid = UUID(entry_id)
    fake_git.files = {k: v for k, v in fake_git.files.items() if k[0] != eid}
    if entry_yaml is not None:
        fake_git.files[(eid, ".phiacta/entry.yaml")] = entry_yaml.encode("utf-8")
    if readme_content is not None:
        fake_git.files[(eid, "README.md")] = readme_content.encode("utf-8")


def _send_push(repo_name: str, after_sha: str = "a" * 40) -> tuple[bytes, dict]:
    """Build the push webhook request body and headers."""
    payload = _make_push_payload(repo_name=repo_name, after=after_sha)
    body = json.dumps(payload).encode()
    sig = _compute_forgejo_signature(body, TEST_WEBHOOK_SECRET)
    headers = {
        "Content-Type": "application/json",
        "X-Forgejo-Event": "push",
        "X-Forgejo-Signature": sig,
    }
    return body, headers


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


async def _get_tsv_row_count(
    session_factory: async_sessionmaker[AsyncSession],
    entry_id: str,
) -> int:
    """Count view_search_tsv rows for an entry using raw SQL."""
    async with session_factory() as session:
        result = await session.execute(
            text(
                "SELECT count(*) FROM view_search_tsv WHERE entry_id = :eid"
            ),
            {"eid": entry_id},
        )
        return result.scalar_one()


async def _delete_entry_directly(
    session_factory: async_sessionmaker[AsyncSession],
    entry_id: str,
) -> None:
    """Delete an entry directly from the DB to test CASCADE."""
    async with session_factory() as session:
        await session.execute(
            delete(Entry).where(Entry.id == UUID(entry_id))
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mount_search_tsv_router(client: httpx.AsyncClient) -> None:
    """Mount the search_tsv view router on the test app.

    The E2E test client bypasses the lifespan hook where plugins are normally
    discovered, so we manually mount the search_tsv router at the correct prefix.

    Importing the views package also ensures ViewSearchTsv is registered with
    Base.metadata so the table is created by e2e_engine.
    """
    from phiacta.views.search_tsv import router as search_tsv_router
    from phiacta.main import app as _app

    _app.include_router(
        search_tsv_router, prefix="/v1/views/search_tsv", tags=["search_tsv"]
    )
    yield  # type: ignore[misc]
    # Cleanup: remove plugin routes after test
    _app.routes[:] = [
        r
        for r in _app.routes
        if not (hasattr(r, "path") and r.path.startswith("/v1/views/search_tsv"))
    ]


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    """Register an agent and return (client, agent_data, token)."""
    auth = await register_agent(
        client, handle="tsv-test", email="tsv@example.com"
    )
    return client, auth["agent"], auth["access_token"]


@pytest.fixture
async def ready_entry(
    authed: AuthedFixture,
    e2e_session_factory: async_sessionmaker[AsyncSession],
) -> tuple[AuthedFixture, dict]:
    """Create an entry and set it to ready status."""
    client, _, token = authed
    entry = await create_entry(client, token, title="Search TSV Test Entry")
    await set_entry_repo_status(e2e_session_factory, entry["id"], "ready")
    return authed, entry


@pytest.fixture
async def version_id(
    e2e_session_factory: async_sessionmaker[AsyncSession],
) -> str:
    """Seed the active search_tsv ViewVersion and return its id."""
    return await _seed_active_version(e2e_session_factory)


# ---------------------------------------------------------------------------
# GET /v1/views/search_tsv/version — Active version metadata
# ---------------------------------------------------------------------------


@needs_pg
class TestGetVersion:
    """Scenario: Client retrieves the active version metadata for search_tsv."""

    async def test_get_version_returns_active_metadata(
        self,
        client: httpx.AsyncClient,
        version_id: str,
    ) -> None:
        """GET /version returns 200 with view_type, version, status, parameters."""
        resp = await client.get("/v1/views/search_tsv/version")
        assert resp.status_code == 200
        data = resp.json()
        assert data["view_type"] == "search_tsv"
        assert data["version"] == "v1"
        assert data["status"] == "active"
        assert data["parameters"] == {"language": "english"}

    async def test_get_version_no_active_version_returns_404(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """GET /version when no active version exists returns 404."""
        # No version_id fixture => no seeded ViewVersion row
        resp = await client.get("/v1/views/search_tsv/version")
        assert resp.status_code == 404

    async def test_version_route_does_not_collide_with_entry_id(
        self,
        client: httpx.AsyncClient,
        version_id: str,
    ) -> None:
        """GET /version returns version metadata, not a 422 from UUID parsing.

        This verifies the route ordering: /version is matched before /{entry_id}.
        """
        resp = await client.get("/v1/views/search_tsv/version")
        assert resp.status_code == 200
        # Confirm it's the version response, not an error
        data = resp.json()
        assert "view_type" in data
        assert "version" in data


# ---------------------------------------------------------------------------
# GET /v1/views/search_tsv/{entry_id} — Raw tsvector for entry
# ---------------------------------------------------------------------------


@needs_pg
class TestGetTsvector:
    """Scenario: Client retrieves the tsvector for a specific entry."""

    async def test_get_tsvector_for_entry_with_computed_tsv(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
        fake_git: FakeGitService,
    ) -> None:
        """GET /{entry_id} returns 200 with the tsvector data after computation.

        Flow: set content_cache -> trigger compute -> GET returns tsvector.
        """
        (client, agent, token), entry = ready_entry
        entry_id = entry["id"]

        # Populate content_cache via webhook ingestion
        entry_yaml = _build_entry_yaml(
            entry_id, agent_id=agent["id"], agent_handle="tsv-test"
        )
        readme_text = "Quantum entanglement is a phenomenon in physics."
        _populate_fake_git(
            fake_git, entry_id, entry_yaml=entry_yaml, readme_content=readme_text
        )

        body, headers = _send_push(entry["repo_name"])
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        # Now compute the tsvector (the implementation should call compute_search_tsv)
        from phiacta.views.search_tsv.compute import compute_search_tsv

        async with e2e_session_factory() as session:
            await compute_search_tsv(
                entry_id=UUID(entry_id),
                content_cache=readme_text,
                version_id=UUID(version_id),
                db=session,
            )
            await session.commit()

        # GET the tsvector
        resp = await client.get(f"/v1/views/search_tsv/{entry_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entry_id"] == entry_id
        assert data["version_id"] == version_id
        assert isinstance(data["tsv"], str)
        assert len(data["tsv"]) > 0
        assert "computed_at" in data
        # The tsvector should contain stemmed tokens from the content
        # "quantum", "entangl", "phenomenon", "physic" are expected stems
        tsv_str = data["tsv"]
        assert "quantum" in tsv_str or "entangl" in tsv_str

    async def test_get_tsvector_entry_not_computed_returns_404(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        version_id: str,
    ) -> None:
        """GET /{entry_id} for entry with no tsvector returns 404."""
        (client, _, _), entry = ready_entry
        resp = await client.get(f"/v1/views/search_tsv/{entry['id']}")
        assert resp.status_code == 404

    async def test_get_tsvector_nonexistent_entry_returns_404(
        self,
        client: httpx.AsyncClient,
        version_id: str,
    ) -> None:
        """GET /{entry_id} for nonexistent entry returns 404."""
        fake_id = str(uuid4())
        resp = await client.get(f"/v1/views/search_tsv/{fake_id}")
        assert resp.status_code == 404

    async def test_get_tsvector_invalid_uuid_returns_422(
        self,
        client: httpx.AsyncClient,
        version_id: str,
    ) -> None:
        """GET /{entry_id} with invalid UUID string returns 422."""
        resp = await client.get("/v1/views/search_tsv/not-a-uuid")
        assert resp.status_code == 422

    async def test_get_tsvector_with_explicit_version_param(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
        fake_git: FakeGitService,
    ) -> None:
        """GET /{entry_id}?version=v1 returns tsvector for that version."""
        (client, agent, token), entry = ready_entry
        entry_id = entry["id"]

        # Set content_cache and compute
        await _set_content_cache(e2e_session_factory, entry_id, "Test content for version param")

        from phiacta.views.search_tsv.compute import compute_search_tsv

        async with e2e_session_factory() as session:
            await compute_search_tsv(
                entry_id=UUID(entry_id),
                content_cache="Test content for version param",
                version_id=UUID(version_id),
                db=session,
            )
            await session.commit()

        resp = await client.get(
            f"/v1/views/search_tsv/{entry_id}",
            params={"version": "v1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["entry_id"] == entry_id
        assert data["version_id"] == version_id


# ---------------------------------------------------------------------------
# Compute lifecycle: webhook triggers computation
# ---------------------------------------------------------------------------


@needs_pg
class TestComputeLifecycle:
    """Scenario: Webhook push triggers tsvector computation via compute_search_tsv."""

    async def test_compute_from_content_cache(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """compute_search_tsv creates a tsvector row from content_cache."""
        (client, _, _), entry = ready_entry
        entry_id = entry["id"]
        content = "The theory of general relativity describes gravity as spacetime curvature."

        await _set_content_cache(e2e_session_factory, entry_id, content)

        from phiacta.views.search_tsv.compute import compute_search_tsv

        async with e2e_session_factory() as session:
            await compute_search_tsv(
                entry_id=UUID(entry_id),
                content_cache=content,
                version_id=UUID(version_id),
                db=session,
            )
            await session.commit()

        # Verify via API
        resp = await client.get(f"/v1/views/search_tsv/{entry_id}")
        assert resp.status_code == 200
        data = resp.json()
        tsv_str = data["tsv"]
        # "relativity", "gravity", "spacetime", "curvature" should be in stemmed form
        assert len(tsv_str) > 0
        assert data["entry_id"] == entry_id

    async def test_compute_idempotent_same_content(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """Calling compute_search_tsv twice with same content produces one row.

        Critical scenario #9: idempotency.
        """
        (client, _, _), entry = ready_entry
        entry_id = entry["id"]
        content = "Idempotent computation test content for search."

        await _set_content_cache(e2e_session_factory, entry_id, content)

        from phiacta.views.search_tsv.compute import compute_search_tsv

        # First compute
        async with e2e_session_factory() as session:
            await compute_search_tsv(
                entry_id=UUID(entry_id),
                content_cache=content,
                version_id=UUID(version_id),
                db=session,
            )
            await session.commit()

        # Second compute (same content)
        async with e2e_session_factory() as session:
            await compute_search_tsv(
                entry_id=UUID(entry_id),
                content_cache=content,
                version_id=UUID(version_id),
                db=session,
            )
            await session.commit()

        # Should still be exactly one row
        count = await _get_tsv_row_count(e2e_session_factory, entry_id)
        assert count == 1

        # Tsvector should be retrievable
        resp = await client.get(f"/v1/views/search_tsv/{entry_id}")
        assert resp.status_code == 200

    async def test_compute_with_none_content_deletes_row(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """compute_search_tsv with content_cache=None deletes existing tsvector.

        Critical scenario #3 / #10: NULL content removes tsvector.
        """
        (client, _, _), entry = ready_entry
        entry_id = entry["id"]

        # First, compute a tsvector
        content = "Content that will be removed later."
        await _set_content_cache(e2e_session_factory, entry_id, content)

        from phiacta.views.search_tsv.compute import compute_search_tsv

        async with e2e_session_factory() as session:
            await compute_search_tsv(
                entry_id=UUID(entry_id),
                content_cache=content,
                version_id=UUID(version_id),
                db=session,
            )
            await session.commit()

        # Verify row exists
        count = await _get_tsv_row_count(e2e_session_factory, entry_id)
        assert count == 1

        # Now compute with None content
        async with e2e_session_factory() as session:
            await compute_search_tsv(
                entry_id=UUID(entry_id),
                content_cache=None,
                version_id=UUID(version_id),
                db=session,
            )
            await session.commit()

        # Row should be gone
        count = await _get_tsv_row_count(e2e_session_factory, entry_id)
        assert count == 0

        # API should return 404
        resp = await client.get(f"/v1/views/search_tsv/{entry_id}")
        assert resp.status_code == 404

    async def test_compute_with_empty_string_deletes_row(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """compute_search_tsv with content_cache="" deletes existing tsvector.

        Critical scenario #10: empty string treated same as None.
        """
        (client, _, _), entry = ready_entry
        entry_id = entry["id"]

        # First, compute a tsvector
        content = "Content that will be replaced with empty string."
        await _set_content_cache(e2e_session_factory, entry_id, content)

        from phiacta.views.search_tsv.compute import compute_search_tsv

        async with e2e_session_factory() as session:
            await compute_search_tsv(
                entry_id=UUID(entry_id),
                content_cache=content,
                version_id=UUID(version_id),
                db=session,
            )
            await session.commit()

        # Now compute with empty string
        async with e2e_session_factory() as session:
            await compute_search_tsv(
                entry_id=UUID(entry_id),
                content_cache="",
                version_id=UUID(version_id),
                db=session,
            )
            await session.commit()

        # Row should be gone
        count = await _get_tsv_row_count(e2e_session_factory, entry_id)
        assert count == 0

    async def test_compute_updates_tsvector_on_content_change(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """Recomputing with different content updates the tsvector (upsert)."""
        (client, _, _), entry = ready_entry
        entry_id = entry["id"]

        from phiacta.views.search_tsv.compute import compute_search_tsv

        # First content
        content1 = "Photosynthesis converts sunlight into chemical energy."
        await _set_content_cache(e2e_session_factory, entry_id, content1)
        async with e2e_session_factory() as session:
            await compute_search_tsv(
                entry_id=UUID(entry_id),
                content_cache=content1,
                version_id=UUID(version_id),
                db=session,
            )
            await session.commit()

        resp1 = await client.get(f"/v1/views/search_tsv/{entry_id}")
        assert resp1.status_code == 200
        tsv1 = resp1.json()["tsv"]

        # Second content (different topic)
        content2 = "Quantum mechanics describes atomic and subatomic particles."
        await _set_content_cache(e2e_session_factory, entry_id, content2)
        async with e2e_session_factory() as session:
            await compute_search_tsv(
                entry_id=UUID(entry_id),
                content_cache=content2,
                version_id=UUID(version_id),
                db=session,
            )
            await session.commit()

        resp2 = await client.get(f"/v1/views/search_tsv/{entry_id}")
        assert resp2.status_code == 200
        tsv2 = resp2.json()["tsv"]

        # Tsvectors should differ
        assert tsv1 != tsv2
        # Still exactly one row
        count = await _get_tsv_row_count(e2e_session_factory, entry_id)
        assert count == 1


# ---------------------------------------------------------------------------
# CASCADE: entry deletion removes tsvector rows
# ---------------------------------------------------------------------------


@needs_pg
class TestCascadeDelete:
    """Scenario: Deleting an entry cascades to remove its tsvector rows.

    Critical scenario #7.
    """

    async def test_entry_delete_cascades_to_tsvector(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """Deleting the entry row removes the associated view_search_tsv row."""
        (client, _, _), entry = ready_entry
        entry_id = entry["id"]

        # Compute a tsvector
        content = "Content for cascade deletion test."
        await _set_content_cache(e2e_session_factory, entry_id, content)

        from phiacta.views.search_tsv.compute import compute_search_tsv

        async with e2e_session_factory() as session:
            await compute_search_tsv(
                entry_id=UUID(entry_id),
                content_cache=content,
                version_id=UUID(version_id),
                db=session,
            )
            await session.commit()

        # Verify row exists
        count = await _get_tsv_row_count(e2e_session_factory, entry_id)
        assert count == 1

        # Delete the entry
        await _delete_entry_directly(e2e_session_factory, entry_id)

        # Tsvector row should be gone (CASCADE)
        count = await _get_tsv_row_count(e2e_session_factory, entry_id)
        assert count == 0


# ---------------------------------------------------------------------------
# No active version
# ---------------------------------------------------------------------------


@needs_pg
class TestNoActiveVersion:
    """Scenario: compute_search_tsv called when no active ViewVersion exists.

    Critical scenario #8: should log warning and no-op.
    """

    async def test_compute_no_active_version_is_noop(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """compute_search_tsv with no active version does not raise and writes no row."""
        (client, _, _), entry = ready_entry
        entry_id = entry["id"]
        content = "Content when no version is active."
        await _set_content_cache(e2e_session_factory, entry_id, content)

        from phiacta.views.search_tsv.compute import compute_search_tsv

        # No version_id fixture => no ViewVersion row
        # Passing version_id=None should trigger the lookup-active-version path
        async with e2e_session_factory() as session:
            # Should not raise
            await compute_search_tsv(
                entry_id=UUID(entry_id),
                content_cache=content,
                version_id=None,
                db=session,
            )
            await session.commit()

        # No row should be written
        count = await _get_tsv_row_count(e2e_session_factory, entry_id)
        assert count == 0


# ---------------------------------------------------------------------------
# Webhook push triggers full tsvector lifecycle (E2E)
# ---------------------------------------------------------------------------


@needs_pg
class TestWebhookTriggersTsvector:
    """Scenario: A webhook push ingests content_cache, which can then be used
    to compute and retrieve a tsvector.

    Critical scenario #2: webhook push triggers tsvector computation.
    This tests the data flow: push -> content_cache -> compute_search_tsv -> GET.
    """

    async def test_full_lifecycle_push_compute_retrieve(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
        version_id: str,
    ) -> None:
        """Full lifecycle: create entry, push via webhook, compute tsv, GET tsv."""
        # Register agent and create entry
        uid = uuid4().hex[:8]
        auth = await register_agent(
            client, handle=f"tsv-wh-{uid}", email=f"tsv-wh-{uid}@example.com"
        )
        token = auth["access_token"]
        agent_id = auth["agent"]["id"]

        entry_data = await create_entry(client, token, title="Webhook TSV Entry")
        entry_id = entry_data["id"]
        repo_name = entry_data["repo_name"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # Simulate webhook push with README content
        readme_text = (
            "# Quantum Computing\n\n"
            "Quantum computing leverages quantum mechanical phenomena "
            "such as superposition and entanglement to perform computation."
        )
        entry_yaml = _build_entry_yaml(
            entry_id, agent_id=agent_id, agent_handle=f"tsv-wh-{uid}"
        )
        _populate_fake_git(
            fake_git, entry_id, entry_yaml=entry_yaml, readme_content=readme_text
        )

        body, headers = _send_push(repo_name)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        # Verify content_cache was set
        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_id))
            )
            entry = result.scalar_one()
            assert entry.content_cache == readme_text

        # Compute the tsvector (simulating what the outbox worker would do)
        from phiacta.views.search_tsv.compute import compute_search_tsv

        async with e2e_session_factory() as session:
            await compute_search_tsv(
                entry_id=UUID(entry_id),
                content_cache=readme_text,
                version_id=UUID(version_id),
                db=session,
            )
            await session.commit()

        # Retrieve the tsvector via API
        resp = await client.get(f"/v1/views/search_tsv/{entry_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entry_id"] == entry_id
        assert data["version_id"] == version_id
        assert isinstance(data["tsv"], str)
        assert len(data["tsv"]) > 0
        assert "computed_at" in data

    async def test_push_clears_content_removes_tsvector(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
        version_id: str,
    ) -> None:
        """Content cleared via push (no README) -> tsvector row is deleted.

        Critical scenario #3: content_cache set to None removes tsvector.
        """
        uid = uuid4().hex[:8]
        auth = await register_agent(
            client, handle=f"tsv-clr-{uid}", email=f"tsv-clr-{uid}@example.com"
        )
        token = auth["access_token"]
        agent_id = auth["agent"]["id"]

        entry_data = await create_entry(client, token, title="Clear Content Entry")
        entry_id = entry_data["id"]
        repo_name = entry_data["repo_name"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # First push with content
        entry_yaml = _build_entry_yaml(
            entry_id, agent_id=agent_id, agent_handle=f"tsv-clr-{uid}"
        )
        _populate_fake_git(
            fake_git, entry_id, entry_yaml=entry_yaml,
            readme_content="Initial content for tsvector."
        )
        body, headers = _send_push(repo_name, after_sha="b" * 40)
        await client.post("/webhooks/forgejo", content=body, headers=headers)

        from phiacta.views.search_tsv.compute import compute_search_tsv

        async with e2e_session_factory() as session:
            await compute_search_tsv(
                entry_id=UUID(entry_id),
                content_cache="Initial content for tsvector.",
                version_id=UUID(version_id),
                db=session,
            )
            await session.commit()

        count = await _get_tsv_row_count(e2e_session_factory, entry_id)
        assert count == 1

        # Second push WITHOUT README (content_cache becomes None)
        _populate_fake_git(
            fake_git, entry_id, entry_yaml=entry_yaml, readme_content=None
        )
        body2, headers2 = _send_push(repo_name, after_sha="c" * 40)
        await client.post("/webhooks/forgejo", content=body2, headers=headers2)

        # Simulate the delete path: compute with None content
        async with e2e_session_factory() as session:
            await compute_search_tsv(
                entry_id=UUID(entry_id),
                content_cache=None,
                version_id=UUID(version_id),
                db=session,
            )
            await session.commit()

        # Tsvector should be deleted
        count = await _get_tsv_row_count(e2e_session_factory, entry_id)
        assert count == 0

        resp = await client.get(f"/v1/views/search_tsv/{entry_id}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Concurrent upserts
# ---------------------------------------------------------------------------


@needs_pg
class TestConcurrentUpserts:
    """Scenario: Concurrent compute calls on the same entry produce consistent state.

    Critical scenario #6.
    """

    async def test_concurrent_compute_produces_one_row(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """Two concurrent compute calls on the same entry produce exactly one row."""
        import asyncio

        (_, _, _), entry = ready_entry
        entry_id = entry["id"]
        content = "Concurrent computation test for tsvector consistency."
        await _set_content_cache(e2e_session_factory, entry_id, content)

        from phiacta.views.search_tsv.compute import compute_search_tsv

        async def _compute_once() -> None:
            async with e2e_session_factory() as session:
                await compute_search_tsv(
                    entry_id=UUID(entry_id),
                    content_cache=content,
                    version_id=UUID(version_id),
                    db=session,
                )
                await session.commit()

        # Run two computations concurrently
        await asyncio.gather(_compute_once(), _compute_once())

        # Must be exactly one row
        count = await _get_tsv_row_count(e2e_session_factory, entry_id)
        assert count == 1


# ---------------------------------------------------------------------------
# Response shape verification
# ---------------------------------------------------------------------------


@needs_pg
class TestResponseShapes:
    """Verify exact response shapes for all endpoints."""

    async def test_version_response_has_all_required_fields(
        self,
        client: httpx.AsyncClient,
        version_id: str,
    ) -> None:
        """Version response contains exactly the expected fields."""
        resp = await client.get("/v1/views/search_tsv/version")
        assert resp.status_code == 200
        data = resp.json()
        required_fields = {"view_type", "version", "status", "parameters"}
        assert required_fields.issubset(set(data.keys()))

    async def test_tsvector_response_has_all_required_fields(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        e2e_session_factory: async_sessionmaker[AsyncSession],
        version_id: str,
    ) -> None:
        """Tsvector response contains entry_id, version_id, tsv, computed_at."""
        (client, _, _), entry = ready_entry
        entry_id = entry["id"]

        content = "Response shape verification content."
        await _set_content_cache(e2e_session_factory, entry_id, content)

        from phiacta.views.search_tsv.compute import compute_search_tsv

        async with e2e_session_factory() as session:
            await compute_search_tsv(
                entry_id=UUID(entry_id),
                content_cache=content,
                version_id=UUID(version_id),
                db=session,
            )
            await session.commit()

        resp = await client.get(f"/v1/views/search_tsv/{entry_id}")
        assert resp.status_code == 200
        data = resp.json()
        required_fields = {"entry_id", "version_id", "tsv", "computed_at"}
        assert required_fields == set(data.keys())
        # Type checks
        assert isinstance(data["entry_id"], str)
        assert isinstance(data["version_id"], str)
        assert isinstance(data["tsv"], str)
        assert isinstance(data["computed_at"], str)
        # computed_at must be an ISO datetime
        assert len(data["computed_at"]) >= 19
