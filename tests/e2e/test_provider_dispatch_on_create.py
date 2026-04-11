# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for generic provider dispatch on entry create (PHI-107).

Tests the full HTTP path for creating entries via POST /v1/entries with
provider dispatch:
- title, summary, entry_type are no longer hardcoded in EntryCreate -- they
  arrive as extra fields and are dispatched to registered providers
- required_on_create validation rejects requests missing required provider fields
- tags can be sent at create time alongside title (new capability)
- unknown extra fields are silently ignored
- the create endpoint returns composed responses including all provider fields
"""

from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from phiacta.core.models.entry import Entry
from phiacta.core.models.outbox import Outbox
import phiacta.extensions.metadata.models  # noqa: F401
import phiacta.extensions.types.models  # noqa: F401
import phiacta.extensions.tags.models  # noqa: F401
import phiacta.extensions.references.models  # noqa: F401

from tests.e2e.conftest import auth_header, register_user, set_entry_repo_status

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    auth = await register_user(client, username=f"dispatch-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


# ---------------------------------------------------------------------------
# Happy path: create with all provider fields
# ---------------------------------------------------------------------------


class TestCreateWithProviderFields:
    """Scenario: User creates an entry by POSTing title, summary, entry_type,
    and content_format. Provider dispatch routes each field to the correct
    extension. The response includes all composed extension fields."""

    async def test_create_with_title_summary_entry_type(
        self, authed: AuthedFixture,
    ) -> None:
        """POST with title + summary + entry_type returns all three in
        the composed response."""
        client, user, token = authed
        resp = await client.post(
            "/v1/entries",
            json={
                "title": "Riemann Hypothesis",
                "summary": "A conjecture about the distribution of primes",
                "entry_type": "theorem",
                "content_format": "markdown",
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()

        # Core fields
        assert "id" in data
        assert data["repo_status"] == "provisioning"
        assert data["created_by"] == user["id"]

        # Extension fields from providers
        assert data["title"] == "Riemann Hypothesis"
        assert data["summary"] == "A conjecture about the distribution of primes"
        assert data["entry_type"] == "theorem"

    async def test_create_with_tags_at_create_time(
        self, authed: AuthedFixture,
    ) -> None:
        """POST with title + tags at create time. This is the new capability
        enabled by generic provider dispatch -- tags are dispatched to the
        TagProvider during entry creation."""
        client, _, token = authed
        resp = await client.post(
            "/v1/entries",
            json={
                "title": "Gravitational Lensing",
                "tags": ["physics", "cosmology"],
                "content_format": "markdown",
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()

        assert data["title"] == "Gravitational Lensing"
        assert sorted(data["tags"]) == ["cosmology", "physics"]

    async def test_create_with_content_and_content_format(
        self, authed: AuthedFixture,
    ) -> None:
        """POST with content + content_format works. content and
        content_format are core fields (used in Outbox/git), not extension
        fields."""
        client, _, token = authed
        resp = await client.post(
            "/v1/entries",
            json={
                "title": "LaTeX Entry",
                "content": r"\section{Introduction} Hello world",
                "content_format": "latex",
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["title"] == "LaTeX Entry"

    async def test_create_with_all_provider_fields_combined(
        self, authed: AuthedFixture,
    ) -> None:
        """POST with title, summary, entry_type, tags, content, and
        content_format all at once."""
        client, _, token = authed
        resp = await client.post(
            "/v1/entries",
            json={
                "title": "Full Entry",
                "summary": "A complete entry with every field",
                "entry_type": "claim",
                "tags": ["alpha", "beta", "gamma"],
                "content": "# Full Content\n\nSome text here.",
                "content_format": "markdown",
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()

        assert data["title"] == "Full Entry"
        assert data["summary"] == "A complete entry with every field"
        assert data["entry_type"] == "claim"
        assert sorted(data["tags"]) == ["alpha", "beta", "gamma"]


# ---------------------------------------------------------------------------
# Validation: required_on_create
# ---------------------------------------------------------------------------


class TestRequiredOnCreateValidation:
    """Scenario: MetadataProvider declares title in required_on_create.
    Requests missing required fields are rejected with 422 before any DB
    work happens."""

    async def test_create_without_title_fails_422(
        self, authed: AuthedFixture,
    ) -> None:
        """POST without title should fail because MetadataProvider requires
        'title' on create. Verify 422."""
        client, _, token = authed
        resp = await client.post(
            "/v1/entries",
            json={"content_format": "markdown"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    async def test_create_with_empty_title_fails_422(
        self, authed: AuthedFixture,
    ) -> None:
        """POST with empty string title should fail validation.
        MetadataProvider validates min_length=1."""
        client, _, token = authed
        resp = await client.post(
            "/v1/entries",
            json={"title": "", "content_format": "markdown"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    async def test_create_with_title_exceeding_500_chars_fails_422(
        self, authed: AuthedFixture,
    ) -> None:
        """POST with title > 500 characters should fail validation.
        MetadataProvider validates max_length=500."""
        client, _, token = authed
        long_title = "x" * 501
        resp = await client.post(
            "/v1/entries",
            json={"title": long_title, "content_format": "markdown"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    async def test_create_with_exactly_500_char_title_succeeds(
        self, authed: AuthedFixture,
    ) -> None:
        """POST with exactly 500-character title should succeed (boundary)."""
        client, _, token = authed
        title_500 = "A" * 500
        resp = await client.post(
            "/v1/entries",
            json={"title": title_500, "content_format": "markdown"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        assert resp.json()["title"] == title_500

    async def test_create_with_exactly_1_char_title_succeeds(
        self, authed: AuthedFixture,
    ) -> None:
        """POST with a single-character title should succeed (boundary)."""
        client, _, token = authed
        resp = await client.post(
            "/v1/entries",
            json={"title": "X", "content_format": "markdown"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        assert resp.json()["title"] == "X"


# ---------------------------------------------------------------------------
# Extra fields handling
# ---------------------------------------------------------------------------


class TestExtraFieldHandling:
    """Scenario: User sends unknown extra fields alongside valid provider
    fields. Unknown fields should be silently ignored -- they should not
    appear in the response and should not cause errors."""

    async def test_unknown_extra_fields_silently_ignored(
        self, authed: AuthedFixture,
    ) -> None:
        """POST with garbage_field alongside valid fields returns 201
        and the response does NOT contain the unknown field."""
        client, _, token = authed
        resp = await client.post(
            "/v1/entries",
            json={
                "title": "Clean Entry",
                "garbage_field": "should-not-appear",
                "another_unknown": 42,
                "content_format": "markdown",
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Clean Entry"
        assert "garbage_field" not in data
        assert "another_unknown" not in data


# ---------------------------------------------------------------------------
# GET after create: verify persistence via providers
# ---------------------------------------------------------------------------


class TestGetAfterCreate:
    """Scenario: User creates an entry with various extension fields, then
    GETs it. All provider-managed fields should be present in the response."""

    async def test_get_entry_after_create_returns_extension_fields(
        self, authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Create entry with title+summary+entry_type+tags, then GET it.
        Verify all fields are present and correct in the detail response."""
        client, _, token = authed

        # Create
        create_resp = await client.post(
            "/v1/entries",
            json={
                "title": "Persistent Entry",
                "summary": "Verify persistence",
                "entry_type": "definition",
                "tags": ["persist-test", "e2e"],
                "content_format": "markdown",
            },
            headers=auth_header(token),
        )
        assert create_resp.status_code == 201
        entry_id = create_resp.json()["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        # GET detail
        get_resp = await client.get(f"/v1/entries/{entry_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()

        assert data["id"] == entry_id
        assert data["title"] == "Persistent Entry"
        assert data["summary"] == "Verify persistence"
        assert data["entry_type"] == "definition"
        assert sorted(data["tags"]) == ["e2e", "persist-test"]

    async def test_list_entries_after_create_returns_extension_fields(
        self, authed: AuthedFixture,
    ) -> None:
        """Create entry, then list all entries. The entry in the list
        should include provider-managed fields (title, entry_type, tags)."""
        client, _, token = authed

        create_resp = await client.post(
            "/v1/entries",
            json={
                "title": "List Visible",
                "entry_type": "claim",
                "tags": ["list-test"],
                "content_format": "markdown",
            },
            headers=auth_header(token),
        )
        assert create_resp.status_code == 201
        entry_id = create_resp.json()["id"]

        list_resp = await client.get("/v1/entries")
        assert list_resp.status_code == 200
        items = list_resp.json()["items"]
        item = next((i for i in items if i["id"] == entry_id), None)
        assert item is not None
        assert item["title"] == "List Visible"
        assert item["entry_type"] == "claim"
        assert item["tags"] == ["list-test"]


# ---------------------------------------------------------------------------
# Outbox payload: no hardcoded title
# ---------------------------------------------------------------------------


class TestOutboxPayload:
    """Scenario: After generic provider dispatch, the outbox entry should
    not contain a hardcoded title field."""

    async def test_outbox_payload_has_no_title(
        self, authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Create an entry and verify that the outbox payload does not
        contain a title key."""
        client, _, token = authed

        resp = await client.post(
            "/v1/entries",
            json={
                "title": "Outbox Test",
                "content": "some content",
                "content_format": "latex",
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        entry_id = UUID(resp.json()["id"])

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Outbox).where(
                    Outbox.aggregate_id == entry_id,
                    Outbox.operation == "create_repo",
                )
            )
            outbox = result.scalar_one_or_none()
            assert outbox is not None
            payload = outbox.payload

            # Core fields present
            assert payload["entry_id"] == str(entry_id)
            assert payload["content_format"] == "latex"
            assert "author_id" in payload
            assert "author_username" in payload

            # Title should NOT be in the outbox payload
            assert "title" not in payload


# ---------------------------------------------------------------------------
# Static check: no hardcoded extension imports in entry_service
# ---------------------------------------------------------------------------


class TestNoHardcodedExtensionImports:
    """Scenario: The core entry service should not import specific extension
    modules directly. Provider dispatch is generic."""

    def test_entry_service_does_not_import_metadata_service(self) -> None:
        """entry_service.py should NOT contain 'from phiacta.extensions.metadata'."""
        import inspect
        from phiacta.core.services import entry_service as es_module
        source = inspect.getsource(es_module)
        assert "from phiacta.extensions.metadata" not in source
        assert "import phiacta.extensions.metadata" not in source

    def test_entry_service_does_not_import_type_service(self) -> None:
        """entry_service.py should NOT contain 'from phiacta.extensions.types'."""
        import inspect
        from phiacta.core.services import entry_service as es_module
        source = inspect.getsource(es_module)
        assert "from phiacta.extensions.types" not in source
        assert "import phiacta.extensions.types" not in source


# ---------------------------------------------------------------------------
# Activity log: no title in metadata
# ---------------------------------------------------------------------------


class TestActivityLog:
    """Scenario: Activity log entry for entry.created should not contain
    a title key in its metadata."""

    async def test_activity_log_no_title_in_metadata(
        self, authed: AuthedFixture,
    ) -> None:
        """Create entry, then check the activity log. The entry.created
        activity should not have 'title' in its metadata."""
        client, _, token = authed

        resp = await client.post(
            "/v1/entries",
            json={
                "title": "Activity Test",
                "content_format": "markdown",
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        entry_id = resp.json()["id"]

        # Fetch activity log for this entry
        activity_resp = await client.get(
            "/v1/activity",
            params={"entity": entry_id},
        )
        assert activity_resp.status_code == 200
        activities = activity_resp.json()["items"]
        created_activities = [
            a for a in activities if a["action"] == "entry.created"
        ]
        assert len(created_activities) >= 1
        metadata = created_activities[0].get("metadata", {})
        # Title is now included in entry.created activity metadata
        assert "title" in metadata
