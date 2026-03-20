# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for the tags extension plugin (NEV-131).

Tests the full API path for:
- PUT  /v1/extensions/tags/{entry_id}  (replace-all tags)
- GET  /v1/extensions/tags/?entry_id=  (list tags for entry)
- GET  /v1/extensions/tags/entries?tags=...&mode=...  (find entries by tags)

Also verifies that the tags field has been removed from the entry layer.
"""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Import tags model at module level so Base.metadata.create_all includes
# the extension_tags table when the e2e_engine fixture runs.
import phiacta.extensions.tags.models  # noqa: F401

from tests.e2e.conftest import (
    auth_header,
    create_entry,
    register_agent,
    set_entry_repo_status,
    set_entry_status,
)

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mount_tags_router(client: httpx.AsyncClient) -> None:
    """Mount the tags extension router on the test app.

    The E2E test client bypasses the lifespan hook where plugins are normally
    discovered, so we manually mount the tags router at the correct prefix.

    Importing the tags package also ensures ExtensionTag is registered with
    Base.metadata so the table is created by e2e_engine.

    Depends on ``client`` to ensure dependency overrides are active.
    """
    from phiacta.extensions.tags import router as tags_router
    from phiacta.main import app as _app

    _app.include_router(
        tags_router, prefix="/v1/extensions/tags", tags=["tags"]
    )
    yield  # type: ignore[misc]
    # Cleanup: remove plugin routes after test
    _app.routes[:] = [
        r for r in _app.routes
        if not (hasattr(r, "path") and r.path.startswith("/v1/extensions/tags"))
    ]


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    """Register an agent and return (client, agent_data, token)."""
    auth = await register_agent(
        client, handle="tags-test", email="tags@example.com"
    )
    return client, auth["agent"], auth["access_token"]


@pytest.fixture
async def ready_entry(
    authed: AuthedFixture,
    e2e_session_factory: async_sessionmaker[AsyncSession],
) -> tuple[AuthedFixture, dict]:
    """Create an entry and set it to ready status."""
    client, _, token = authed
    entry = await create_entry(client, token, title="Tags Test Entry")
    await set_entry_repo_status(e2e_session_factory, entry["id"], "ready")
    return authed, entry


# ---------------------------------------------------------------------------
# Happy path: Set and list tags
# ---------------------------------------------------------------------------


class TestSetTags:
    """Scenario: Entry owner sets tags on their entry via PUT."""

    async def test_set_tags_on_entry(
        self,
        ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """PUT with a list of tags returns 200 with the correct response shape."""
        (client, _, token), entry = ready_entry
        entry_id = entry["id"]

        resp = await client.put(
            f"/v1/extensions/tags/{entry_id}",
            json={"tags": ["physics", "quantum-mechanics", "entanglement"]},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["entry_id"] == entry_id
        assert isinstance(data["tags"], list)
        assert len(data["tags"]) == 3
        tag_names = [t["tag"] for t in data["tags"]]
        assert "physics" in tag_names
        assert "quantum-mechanics" in tag_names
        assert "entanglement" in tag_names
        # Each tag must have created_by and created_at
        for tag_obj in data["tags"]:
            assert "tag" in tag_obj
            assert "created_by" in tag_obj
            assert "created_at" in tag_obj

    async def test_set_tags_response_shape_tag_response(
        self,
        ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Each tag object in the response has tag, created_by (UUID), created_at (ISO datetime)."""
        (client, agent, token), entry = ready_entry
        entry_id = entry["id"]

        resp = await client.put(
            f"/v1/extensions/tags/{entry_id}",
            json={"tags": ["relativity"]},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        tag_obj = data["tags"][0]
        assert tag_obj["tag"] == "relativity"
        assert tag_obj["created_by"] == agent["id"]
        # created_at must be a parseable ISO datetime string
        assert len(tag_obj["created_at"]) >= 19  # at least YYYY-MM-DDTHH:MM:SS


class TestListTags:
    """Scenario: Anyone can list tags for an entry."""

    async def test_list_tags_for_entry(
        self,
        ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """GET /v1/extensions/tags/?entry_id=... returns tags previously set."""
        (client, _, token), entry = ready_entry
        entry_id = entry["id"]

        # Set tags first
        await client.put(
            f"/v1/extensions/tags/{entry_id}",
            json={"tags": ["mathematics", "algebra"]},
            headers=auth_header(token),
        )

        # List without auth (public)
        resp = await client.get(
            "/v1/extensions/tags/",
            params={"entry_id": entry_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["entry_id"] == entry_id
        tag_names = [t["tag"] for t in data["tags"]]
        assert "mathematics" in tag_names
        assert "algebra" in tag_names

    async def test_list_tags_for_entry_with_no_tags(
        self,
        ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Listing tags for an entry with no tags returns an empty list."""
        (client, _, _), entry = ready_entry

        resp = await client.get(
            "/v1/extensions/tags/",
            params={"entry_id": entry["id"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tags"] == []


class TestReplaceTags:
    """Scenario: PUT replaces all tags atomically."""

    async def test_replace_tags_removes_old(
        self,
        ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Setting tags twice replaces the first set entirely."""
        (client, _, token), entry = ready_entry
        entry_id = entry["id"]

        # First set
        await client.put(
            f"/v1/extensions/tags/{entry_id}",
            json={"tags": ["old-tag-1", "old-tag-2"]},
            headers=auth_header(token),
        )

        # Replace with new set
        resp = await client.put(
            f"/v1/extensions/tags/{entry_id}",
            json={"tags": ["new-tag-1"]},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        tag_names = [t["tag"] for t in resp.json()["tags"]]
        assert tag_names == ["new-tag-1"]

        # Verify old tags are gone via list
        list_resp = await client.get(
            "/v1/extensions/tags/",
            params={"entry_id": entry_id},
        )
        list_tag_names = [t["tag"] for t in list_resp.json()["tags"]]
        assert "old-tag-1" not in list_tag_names
        assert "old-tag-2" not in list_tag_names
        assert "new-tag-1" in list_tag_names

    async def test_clear_all_tags(
        self,
        ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """PUT with empty list clears all tags on the entry."""
        (client, _, token), entry = ready_entry
        entry_id = entry["id"]

        # Set some tags
        await client.put(
            f"/v1/extensions/tags/{entry_id}",
            json={"tags": ["to-be-cleared"]},
            headers=auth_header(token),
        )

        # Clear all
        resp = await client.put(
            f"/v1/extensions/tags/{entry_id}",
            json={"tags": []},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["tags"] == []

        # Verify cleared
        list_resp = await client.get(
            "/v1/extensions/tags/",
            params={"entry_id": entry_id},
        )
        assert list_resp.json()["tags"] == []


# ---------------------------------------------------------------------------
# Find entries by tags
# ---------------------------------------------------------------------------


class TestFindEntriesByTags:
    """Scenario: Discovery via tag-based search."""

    async def test_find_entries_or_mode(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """OR mode returns entries with ANY matching tag."""
        auth = await register_agent(
            client, handle="find-or", email="findor@example.com"
        )
        token = auth["access_token"]

        # Create two entries with different tags
        entry_a = await create_entry(client, token, title="Entry A - Physics")
        await set_entry_repo_status(e2e_session_factory, entry_a["id"], "ready")
        await client.put(
            f"/v1/extensions/tags/{entry_a['id']}",
            json={"tags": ["physics"]},
            headers=auth_header(token),
        )

        entry_b = await create_entry(client, token, title="Entry B - Math")
        await set_entry_repo_status(e2e_session_factory, entry_b["id"], "ready")
        await client.put(
            f"/v1/extensions/tags/{entry_b['id']}",
            json={"tags": ["mathematics"]},
            headers=auth_header(token),
        )

        # Search for either tag with OR mode
        resp = await client.get(
            "/v1/extensions/tags/entries",
            params={"tags": "physics,mathematics", "mode": "or"},
        )
        assert resp.status_code == 200
        data = resp.json()
        found_ids = [item["entry_id"] for item in data["items"]]
        assert entry_a["id"] in found_ids
        assert entry_b["id"] in found_ids

    async def test_find_entries_and_mode(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """AND mode returns only entries with ALL matching tags."""
        auth = await register_agent(
            client, handle="find-and", email="findand@example.com"
        )
        token = auth["access_token"]

        entry_both = await create_entry(client, token, title="Both Tags")
        await set_entry_repo_status(
            e2e_session_factory, entry_both["id"], "ready"
        )
        await client.put(
            f"/v1/extensions/tags/{entry_both['id']}",
            json={"tags": ["physics", "mathematics"]},
            headers=auth_header(token),
        )

        entry_one = await create_entry(client, token, title="One Tag Only")
        await set_entry_repo_status(
            e2e_session_factory, entry_one["id"], "ready"
        )
        await client.put(
            f"/v1/extensions/tags/{entry_one['id']}",
            json={"tags": ["physics"]},
            headers=auth_header(token),
        )

        # AND mode: only entry_both has both tags
        resp = await client.get(
            "/v1/extensions/tags/entries",
            params={"tags": "physics,mathematics", "mode": "and"},
        )
        assert resp.status_code == 200
        data = resp.json()
        found_ids = [item["entry_id"] for item in data["items"]]
        assert entry_both["id"] in found_ids
        assert entry_one["id"] not in found_ids

    async def test_find_entries_no_matches(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """Search for non-existent tag returns empty paginated response."""
        resp = await client.get(
            "/v1/extensions/tags/entries",
            params={"tags": "nonexistent-tag-xyz"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        # Verify pagination shape
        assert "limit" in data
        assert "offset" in data
        assert "has_more" in data

    async def test_find_entries_pagination(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Find-by-tags supports limit and offset pagination."""
        auth = await register_agent(
            client, handle="find-page", email="findpage@example.com"
        )
        token = auth["access_token"]

        # Create 5 entries with the same tag
        created_ids = []
        for i in range(5):
            entry = await create_entry(
                client, token, title=f"Paginated Entry {i}"
            )
            await set_entry_repo_status(
                e2e_session_factory, entry["id"], "ready"
            )
            await client.put(
                f"/v1/extensions/tags/{entry['id']}",
                json={"tags": ["pagination-test"]},
                headers=auth_header(token),
            )
            created_ids.append(entry["id"])

        # Get first page
        resp = await client.get(
            "/v1/extensions/tags/entries",
            params={"tags": "pagination-test", "limit": 2, "offset": 0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] == 5
        assert data["has_more"] is True

        # Get second page
        resp2 = await client.get(
            "/v1/extensions/tags/entries",
            params={"tags": "pagination-test", "limit": 2, "offset": 2},
        )
        data2 = resp2.json()
        assert len(data2["items"]) == 2

        # Pages should not overlap
        page1_ids = {item["entry_id"] for item in data["items"]}
        page2_ids = {item["entry_id"] for item in data2["items"]}
        assert page1_ids.isdisjoint(page2_ids)

    async def test_find_entries_response_shape(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Each item in find-by-tags response has entry_id and title."""
        auth = await register_agent(
            client, handle="find-shape", email="findshape@example.com"
        )
        token = auth["access_token"]

        entry = await create_entry(client, token, title="Shape Check Entry")
        await set_entry_repo_status(
            e2e_session_factory, entry["id"], "ready"
        )
        await client.put(
            f"/v1/extensions/tags/{entry['id']}",
            json={"tags": ["shape-test"]},
            headers=auth_header(token),
        )

        resp = await client.get(
            "/v1/extensions/tags/entries",
            params={"tags": "shape-test"},
        )
        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert "entry_id" in item
        assert "title" in item
        assert item["entry_id"] == entry["id"]
        assert item["title"] == "Shape Check Entry"

    async def test_find_entries_archived_excluded_by_default(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Archived entries are excluded from find-by-tags by default."""
        auth = await register_agent(
            client, handle="find-arch", email="findarch@example.com"
        )
        token = auth["access_token"]

        entry = await create_entry(client, token, title="To Be Archived")
        await set_entry_repo_status(
            e2e_session_factory, entry["id"], "ready"
        )
        await client.put(
            f"/v1/extensions/tags/{entry['id']}",
            json={"tags": ["archive-filter-test"]},
            headers=auth_header(token),
        )

        # Archive the entry
        await set_entry_status(e2e_session_factory, entry["id"], "archived")

        # Default search should exclude it
        resp = await client.get(
            "/v1/extensions/tags/entries",
            params={"tags": "archive-filter-test"},
        )
        assert resp.status_code == 200
        found_ids = [item["entry_id"] for item in resp.json()["items"]]
        assert entry["id"] not in found_ids

    async def test_find_entries_archived_included_with_flag(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Archived entries are included when include_archived=true."""
        auth = await register_agent(
            client, handle="find-incl", email="findincl@example.com"
        )
        token = auth["access_token"]

        entry = await create_entry(client, token, title="Archived Included")
        await set_entry_repo_status(
            e2e_session_factory, entry["id"], "ready"
        )
        await client.put(
            f"/v1/extensions/tags/{entry['id']}",
            json={"tags": ["archive-include-test"]},
            headers=auth_header(token),
        )

        await set_entry_status(e2e_session_factory, entry["id"], "archived")

        # With include_archived=true
        resp = await client.get(
            "/v1/extensions/tags/entries",
            params={
                "tags": "archive-include-test",
                "include_archived": "true",
            },
        )
        assert resp.status_code == 200
        found_ids = [item["entry_id"] for item in resp.json()["items"]]
        assert entry["id"] in found_ids


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


class TestTagsAuthorization:
    """Authorization checks for tag operations."""

    async def test_put_unauthenticated_returns_401(
        self,
        ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """PUT without auth token returns 401."""
        (client, _, _), entry = ready_entry

        resp = await client.put(
            f"/v1/extensions/tags/{entry['id']}",
            json={"tags": ["should-fail"]},
        )
        assert resp.status_code == 401

    async def test_put_non_owner_returns_403(
        self,
        ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """PUT by a non-owner agent returns 403."""
        (client, _, _), entry = ready_entry

        other = await register_agent(
            client, handle="non-owner-tags", email="nonowner@example.com"
        )
        resp = await client.put(
            f"/v1/extensions/tags/{entry['id']}",
            json={"tags": ["hijack"]},
            headers=auth_header(other["access_token"]),
        )
        assert resp.status_code == 403

    async def test_get_list_unauthenticated_returns_200(
        self,
        ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """GET /v1/extensions/tags/ (list) is public — no auth required."""
        (client, _, _), entry = ready_entry

        resp = await client.get(
            "/v1/extensions/tags/",
            params={"entry_id": entry["id"]},
        )
        assert resp.status_code == 200

    async def test_get_find_entries_unauthenticated_returns_200(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """GET /v1/extensions/tags/entries is public — no auth required."""
        resp = await client.get(
            "/v1/extensions/tags/entries",
            params={"tags": "any-tag"},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Validation and edge cases
# ---------------------------------------------------------------------------


class TestTagValidation:
    """Input validation for tag operations."""

    async def test_put_entry_not_found_returns_404(
        self,
        authed: AuthedFixture,
    ) -> None:
        """PUT on nonexistent entry returns 404."""
        client, _, token = authed
        fake_id = str(uuid4())

        resp = await client.put(
            f"/v1/extensions/tags/{fake_id}",
            json={"tags": ["orphan"]},
            headers=auth_header(token),
        )
        assert resp.status_code == 404

    async def test_put_entry_not_ready_returns_409(
        self,
        authed: AuthedFixture,
    ) -> None:
        """PUT on an entry whose repo_status != 'ready' returns 409."""
        client, _, token = authed
        entry = await create_entry(client, token, title="Not Ready")
        # Entry is still provisioning — not ready

        resp = await client.put(
            f"/v1/extensions/tags/{entry['id']}",
            json={"tags": ["should-fail"]},
            headers=auth_header(token),
        )
        assert resp.status_code == 409

    async def test_tag_too_long_returns_422(
        self,
        ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Tag longer than 200 characters is rejected."""
        (client, _, token), entry = ready_entry
        long_tag = "a" * 201

        resp = await client.put(
            f"/v1/extensions/tags/{entry['id']}",
            json={"tags": [long_tag]},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    async def test_tag_exactly_200_chars_accepted(
        self,
        ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Tag of exactly 200 characters is accepted."""
        (client, _, token), entry = ready_entry
        max_tag = "a" * 200

        resp = await client.put(
            f"/v1/extensions/tags/{entry['id']}",
            json={"tags": [max_tag]},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        tag_names = [t["tag"] for t in resp.json()["tags"]]
        assert max_tag in tag_names

    async def test_empty_string_tag_returns_422(
        self,
        ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """An empty string as a tag value is rejected."""
        (client, _, token), entry = ready_entry

        resp = await client.put(
            f"/v1/extensions/tags/{entry['id']}",
            json={"tags": ["valid", ""]},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    async def test_tag_with_comma_returns_422(
        self,
        ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Tags containing commas are rejected (comma is the query separator)."""
        (client, _, token), entry = ready_entry

        resp = await client.put(
            f"/v1/extensions/tags/{entry['id']}",
            json={"tags": ["physics,math"]},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    async def test_more_than_50_tags_rejected(
        self,
        ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """More than 50 tags per entry is rejected."""
        (client, _, token), entry = ready_entry
        tags_51 = [f"tag-{i}" for i in range(51)]

        resp = await client.put(
            f"/v1/extensions/tags/{entry['id']}",
            json={"tags": tags_51},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    async def test_exactly_50_tags_accepted(
        self,
        ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Exactly 50 tags per entry is accepted."""
        (client, _, token), entry = ready_entry
        tags_50 = [f"tag-{i}" for i in range(50)]

        resp = await client.put(
            f"/v1/extensions/tags/{entry['id']}",
            json={"tags": tags_50},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        assert len(resp.json()["tags"]) == 50

    async def test_more_than_10_tags_in_search_rejected(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """Search query with more than 10 tags is rejected."""
        tags_11 = ",".join(f"tag-{i}" for i in range(11))

        resp = await client.get(
            "/v1/extensions/tags/entries",
            params={"tags": tags_11},
        )
        assert resp.status_code == 422

    async def test_exactly_10_tags_in_search_accepted(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """Search query with exactly 10 tags is accepted."""
        tags_10 = ",".join(f"tag-{i}" for i in range(10))

        resp = await client.get(
            "/v1/extensions/tags/entries",
            params={"tags": tags_10},
        )
        assert resp.status_code == 200


class TestTagNormalization:
    """Tag normalization: lowercase, strip whitespace, deduplicate."""

    async def test_tags_normalized_to_lowercase(
        self,
        ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Tags are lowercased: 'Physics' becomes 'physics'."""
        (client, _, token), entry = ready_entry

        resp = await client.put(
            f"/v1/extensions/tags/{entry['id']}",
            json={"tags": ["Physics", "QUANTUM", "Theory"]},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        tag_names = sorted(t["tag"] for t in resp.json()["tags"])
        assert tag_names == ["physics", "quantum", "theory"]

    async def test_duplicate_tags_after_normalization_deduplicated(
        self,
        ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Duplicate tags after case-normalization produce only one tag."""
        (client, _, token), entry = ready_entry

        resp = await client.put(
            f"/v1/extensions/tags/{entry['id']}",
            json={"tags": ["physics", "Physics", "PHYSICS"]},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        tag_names = [t["tag"] for t in resp.json()["tags"]]
        assert tag_names == ["physics"]

    async def test_whitespace_stripped_from_tags(
        self,
        ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Leading and trailing whitespace is stripped from tags."""
        (client, _, token), entry = ready_entry

        resp = await client.put(
            f"/v1/extensions/tags/{entry['id']}",
            json={"tags": ["  physics  ", " math "]},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        tag_names = sorted(t["tag"] for t in resp.json()["tags"])
        assert tag_names == ["math", "physics"]

    async def test_whitespace_only_tags_filtered_out(
        self,
        ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """Tags that are only whitespace are silently filtered out."""
        (client, _, token), entry = ready_entry

        resp = await client.put(
            f"/v1/extensions/tags/{entry['id']}",
            json={"tags": ["valid", "   ", "\t", "also-valid"]},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        tag_names = sorted(t["tag"] for t in resp.json()["tags"])
        assert tag_names == ["also-valid", "valid"]


# ---------------------------------------------------------------------------
# Tags persist independently of entry metadata
# ---------------------------------------------------------------------------


class TestTagsPersistence:
    """Tags persist independently of entry metadata operations."""

    async def test_tags_survive_entry_metadata_update(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        fake_git,  # type: ignore[type-arg]
    ) -> None:
        """Tags set via the extension are not affected by PATCH /entries/{id}."""
        (client, agent, token), entry = ready_entry
        entry_id = entry["id"]

        # Set tags via extension
        await client.put(
            f"/v1/extensions/tags/{entry_id}",
            json={"tags": ["persistent-tag"]},
            headers=auth_header(token),
        )

        # Seed entry.yaml for the PATCH endpoint
        from uuid import UUID
        import yaml
        yaml_bytes = yaml.dump({
            "entry_id": f"ent_{entry_id}",
            "schema_version": 1,
            "title": "Tags Test Entry",
            "author": {"id": f"usr_{agent['id']}", "name": "tags-test"},
            "created_at": "2026-01-01T00:00:00",
            "content_format": "markdown",
        }, default_flow_style=False, allow_unicode=True, sort_keys=False).encode()
        fake_git.files[(UUID(entry_id), ".phiacta/entry.yaml")] = yaml_bytes

        # Update entry metadata (should not affect tags)
        await client.patch(
            f"/v1/entries/{entry_id}",
            json={"title": "Updated Title"},
            headers=auth_header(token),
        )

        # Tags should still be there
        resp = await client.get(
            "/v1/extensions/tags/",
            params={"entry_id": entry_id},
        )
        assert resp.status_code == 200
        tag_names = [t["tag"] for t in resp.json()["tags"]]
        assert "persistent-tag" in tag_names


# ---------------------------------------------------------------------------
# Entry layer removal verification
# ---------------------------------------------------------------------------


class TestEntryLayerTagRemoval:
    """Verify that 'tags' field has been removed from the entry layer."""

    async def test_create_entry_does_not_accept_tags(
        self,
        authed: AuthedFixture,
    ) -> None:
        """POST /v1/entries should either reject or ignore 'tags' in the body.

        After the migration, the entry create endpoint should not process tags.
        We verify the response does not include a 'tags' field.
        """
        client, _, token = authed

        resp = await client.post(
            "/v1/entries",
            json={"title": "No Tags Entry", "tags": ["should-be-ignored"]},
            headers=auth_header(token),
        )
        # Either 201 (ignoring tags) or 422 (rejecting tags) is acceptable.
        # But the response should not contain a 'tags' key.
        if resp.status_code == 201:
            data = resp.json()
            assert "tags" not in data, (
                "Entry response should no longer include 'tags' field"
            )

    async def test_list_entries_response_has_no_tags(
        self,
        authed: AuthedFixture,
    ) -> None:
        """GET /v1/entries items should not include 'tags' field."""
        client, _, token = authed

        await create_entry(client, token, title="List Check Entry")

        resp = await client.get("/v1/entries")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 1
        for item in items:
            assert "tags" not in item, (
                "Entry list item should no longer include 'tags' field"
            )

    async def test_get_entry_response_has_no_tags(
        self,
        authed: AuthedFixture,
    ) -> None:
        """GET /v1/entries/{id} should not include 'tags' field."""
        client, _, token = authed

        entry = await create_entry(client, token, title="Detail Check Entry")
        resp = await client.get(f"/v1/entries/{entry['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert "tags" not in data, (
            "Entry detail response should no longer include 'tags' field"
        )

    async def test_update_entry_does_not_accept_tags(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        fake_git,  # type: ignore[type-arg]
    ) -> None:
        """PATCH /v1/entries/{id} should either reject or ignore 'tags'."""
        (client, agent, token), entry = ready_entry
        entry_id = entry["id"]

        # Seed entry.yaml for PATCH
        from uuid import UUID
        import yaml
        yaml_bytes = yaml.dump({
            "entry_id": f"ent_{entry_id}",
            "schema_version": 1,
            "title": "Tags Test Entry",
            "author": {"id": f"usr_{agent['id']}", "name": "tags-test"},
            "created_at": "2026-01-01T00:00:00",
            "content_format": "markdown",
        }, default_flow_style=False, allow_unicode=True, sort_keys=False).encode()
        fake_git.files[(UUID(entry_id), ".phiacta/entry.yaml")] = yaml_bytes

        resp = await client.patch(
            f"/v1/entries/{entry_id}",
            json={"tags": ["should-be-ignored"]},
            headers=auth_header(token),
        )
        # Should succeed but tags should not appear in the response
        if resp.status_code == 200:
            data = resp.json()
            assert "tags" not in data, (
                "Entry update response should no longer include 'tags' field"
            )
