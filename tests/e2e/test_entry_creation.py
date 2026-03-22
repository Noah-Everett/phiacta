# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for entry creation with outbox integration (NEV-117).

Tests the full API contract for POST /v1/entries, including:
- Response shape and status codes
- Outbox row creation with correct payload
- Atomicity of entry + outbox row creation
- Validation and error handling
"""

from __future__ import annotations

import json
from typing import TypeAlias
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from phiacta.core.models.entry import Entry
from phiacta.core.models.outbox import Outbox
from tests.e2e.conftest import auth_header, register_user

AuthedFixture: TypeAlias = tuple[httpx.AsyncClient, dict, str]


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    """Register a user and return (client, user_data, token)."""
    uid = uuid4().hex[:8]
    auth = await register_user(
        client, handle=f"create-{uid}"
    )
    return client, auth["user"], auth["access_token"]


class TestCreateEntryMinimal:
    """Scenario: User creates an entry with only required fields."""

    async def test_create_entry_minimal(self, authed: AuthedFixture) -> None:
        """POST with only required fields returns 201 with provisioning status."""
        client, user, token = authed
        resp = await client.post(
            "/v1/entries",
            json={"title": "Minimal Entry", "content_format": "markdown"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Minimal Entry"
        assert data["content_format"] == "markdown"
        assert data["repo_status"] == "provisioning"
        assert data["created_by"] == user["id"]
        # Optional fields should be absent/null/default
        assert data["layout_hint"] is None
        assert data["summary"] is None
        assert data["license"] is None
        assert data["content_cache"] is None
        assert "tags" not in data
        assert data["forgejo_repo_id"] is None
        assert data["current_head_sha"] is None

    async def test_create_entry_default_values(self, authed: AuthedFixture) -> None:
        """Verify defaults: repo_status=provisioning, status=active, schema_version=1."""
        client, _, token = authed
        resp = await client.post(
            "/v1/entries",
            json={"title": "Defaults Check"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["repo_status"] == "provisioning"
        assert data["status"] == "active"
        assert data["schema_version"] == 1
        assert data["content_cache"] is None


class TestCreateEntryFull:
    """Scenario: User creates an entry with all optional fields populated."""

    async def test_create_entry_full(self, authed: AuthedFixture) -> None:
        """POST with all fields returns 201 with all fields populated in response."""
        client, user, token = authed
        resp = await client.post(
            "/v1/entries",
            json={
                "title": "Comprehensive Thermodynamics Review",
                "content_format": "latex",
                "layout_hint": "review-paper",
                "summary": "A comprehensive review of modern thermodynamics.",
                "license": "CC-BY-SA-4.0",
                "content": "\\section{Introduction}\nThermodynamics is...",
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Comprehensive Thermodynamics Review"
        assert data["content_format"] == "latex"
        assert data["layout_hint"] == "review-paper"
        assert data["summary"] == "A comprehensive review of modern thermodynamics."
        assert data["license"] == "CC-BY-SA-4.0"
        assert data["repo_status"] == "provisioning"
        assert data["created_by"] == user["id"]
        # id, created_at, updated_at should be present
        assert data["id"] is not None
        assert data["created_at"] is not None
        assert data["updated_at"] is not None

    async def test_create_entry_with_content(self, authed: AuthedFixture) -> None:
        """POST with content field stores it for outbox processing."""
        client, _, token = authed
        content_body = "# My Research\n\nThis is the initial README content."
        resp = await client.post(
            "/v1/entries",
            json={
                "title": "Entry With Content",
                "content_format": "markdown",
                "content": content_body,
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 201

    async def test_create_entry_plain_format(self, authed: AuthedFixture) -> None:
        """POST with content_format=plain is accepted."""
        client, _, token = authed
        resp = await client.post(
            "/v1/entries",
            json={"title": "Plain Text Entry", "content_format": "plain"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        assert resp.json()["content_format"] == "plain"

    async def test_create_entry_latex_format(self, authed: AuthedFixture) -> None:
        """POST with content_format=latex is accepted."""
        client, _, token = authed
        resp = await client.post(
            "/v1/entries",
            json={"title": "LaTeX Entry", "content_format": "latex"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        assert resp.json()["content_format"] == "latex"


class TestCreateEntryRepoName:
    """Scenario: repo_name is the entry UUID string, not the user handle."""

    async def test_create_entry_repo_name_is_uuid(self, authed: AuthedFixture) -> None:
        """repo_name must equal the entry's id as a string (UUID format)."""
        client, _, token = authed
        resp = await client.post(
            "/v1/entries",
            json={"title": "UUID Repo Name Test"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        data = resp.json()
        entry_id = data["id"]
        repo_name = data["repo_name"]
        # repo_name should be the UUID string of the entry id
        assert repo_name == entry_id
        # Verify it's a valid UUID
        UUID(repo_name)

    async def test_create_entry_two_entries_unique_repo_names(
        self, authed: AuthedFixture
    ) -> None:
        """Same user creates two entries, each gets a unique repo_name."""
        client, _, token = authed
        headers = auth_header(token)
        resp_a = await client.post(
            "/v1/entries", json={"title": "Entry Alpha"}, headers=headers
        )
        resp_b = await client.post(
            "/v1/entries", json={"title": "Entry Beta"}, headers=headers
        )
        assert resp_a.status_code == 201
        assert resp_b.status_code == 201
        repo_a = resp_a.json()["repo_name"]
        repo_b = resp_b.json()["repo_name"]
        assert repo_a != repo_b
        # Both should be valid UUIDs
        UUID(repo_a)
        UUID(repo_b)


class TestCreateEntryOutbox:
    """Scenario: Entry creation atomically writes an outbox row for repo provisioning."""

    async def test_create_entry_creates_outbox_row(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """After POST, an outbox row exists with operation=create_repo."""
        client, _, token = authed
        resp = await client.post(
            "/v1/entries",
            json={"title": "Outbox Row Test"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        entry_id = resp.json()["id"]

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Outbox).where(Outbox.aggregate_id == UUID(entry_id))
            )
            outbox_row = result.scalar_one_or_none()
            assert outbox_row is not None
            assert outbox_row.operation == "create_repo"
            assert outbox_row.aggregate_type == "entry"
            assert outbox_row.status == "pending"
            assert outbox_row.attempts == 0

    async def test_create_entry_outbox_payload_complete(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Outbox payload must contain all required fields for repo provisioning."""
        client, user, token = authed
        resp = await client.post(
            "/v1/entries",
            json={
                "title": "Payload Completeness Test",
                "content_format": "latex",
                "layout_hint": "theorem",
                "summary": "A foundational theorem.",
                "license": "CC-BY-4.0",
                "content": "\\begin{theorem}\nLet G be a group...\n\\end{theorem}",
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        entry_data = resp.json()
        entry_id = entry_data["id"]

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Outbox).where(Outbox.aggregate_id == UUID(entry_id))
            )
            outbox_row = result.scalar_one()
            payload = outbox_row.payload

            # All required payload fields
            assert payload["entry_id"] == entry_id
            assert payload["title"] == "Payload Completeness Test"
            assert payload["content_format"] == "latex"
            assert payload["author_id"] == user["id"]
            assert payload["author_handle"] == user["handle"]
            assert payload["summary"] == "A foundational theorem."
            assert payload["license"] == "CC-BY-4.0"
            assert payload["layout_hint"] == "theorem"
            assert (
                payload["content"]
                == "\\begin{theorem}\nLet G be a group...\n\\end{theorem}"
            )
            assert "created_at" in payload

    async def test_create_entry_outbox_payload_with_defaults(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Outbox payload includes fields even when optional values are defaults/null."""
        client, user, token = authed
        resp = await client.post(
            "/v1/entries",
            json={"title": "Minimal Payload Test", "content_format": "markdown"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        entry_id = resp.json()["id"]

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Outbox).where(Outbox.aggregate_id == UUID(entry_id))
            )
            outbox_row = result.scalar_one()
            payload = outbox_row.payload

            # Required fields present even for minimal creation
            assert payload["entry_id"] == entry_id
            assert payload["title"] == "Minimal Payload Test"
            assert payload["content_format"] == "markdown"
            assert payload["author_id"] == user["id"]
            assert payload["author_handle"] == user["handle"]
            assert "created_at" in payload
            # Optional fields present (as null or empty)
            assert "summary" in payload
            assert "license" in payload
            assert "layout_hint" in payload
            assert "content" in payload

    async def test_create_entry_atomicity(
        self,
        authed: AuthedFixture,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Entry and outbox rows are both present after creation (same transaction)."""
        client, _, token = authed
        resp = await client.post(
            "/v1/entries",
            json={"title": "Atomicity Test"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        entry_id = UUID(resp.json()["id"])

        async with e2e_session_factory() as session:
            # Entry row exists
            entry_result = await session.execute(
                select(Entry).where(Entry.id == entry_id)
            )
            entry_row = entry_result.scalar_one_or_none()
            assert entry_row is not None
            assert entry_row.repo_status == "provisioning"
            assert entry_row.repo_name == str(entry_id)

            # Outbox row exists for the same entry
            outbox_result = await session.execute(
                select(Outbox).where(Outbox.aggregate_id == entry_id)
            )
            outbox_row = outbox_result.scalar_one_or_none()
            assert outbox_row is not None
            assert outbox_row.operation == "create_repo"


class TestCreateEntryValidation:
    """Scenario: Invalid requests are properly rejected with appropriate status codes."""

    async def test_create_entry_unauthenticated(
        self, client: httpx.AsyncClient
    ) -> None:
        """POST without auth token returns 401."""
        resp = await client.post(
            "/v1/entries",
            json={"title": "No Auth Entry", "content_format": "markdown"},
        )
        assert resp.status_code == 401

    async def test_create_entry_invalid_content_format(
        self, authed: AuthedFixture
    ) -> None:
        """POST with content_format not in [markdown, latex, plain] returns 422."""
        client, _, token = authed
        resp = await client.post(
            "/v1/entries",
            json={"title": "Bad Format", "content_format": "docx"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    async def test_create_entry_invalid_content_format_html(
        self, authed: AuthedFixture
    ) -> None:
        """POST with content_format=html is also rejected."""
        client, _, token = authed
        resp = await client.post(
            "/v1/entries",
            json={"title": "HTML Entry", "content_format": "html"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    async def test_create_entry_empty_title(self, authed: AuthedFixture) -> None:
        """POST with empty title returns 422."""
        client, _, token = authed
        resp = await client.post(
            "/v1/entries",
            json={"title": "", "content_format": "markdown"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    async def test_create_entry_missing_title(self, authed: AuthedFixture) -> None:
        """POST without title returns 422."""
        client, _, token = authed
        resp = await client.post(
            "/v1/entries",
            json={"content_format": "markdown"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    async def test_create_entry_title_too_long(self, authed: AuthedFixture) -> None:
        """POST with title > 500 chars returns 422."""
        client, _, token = authed
        resp = await client.post(
            "/v1/entries",
            json={"title": "x" * 501, "content_format": "markdown"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    async def test_create_entry_title_exactly_500(self, authed: AuthedFixture) -> None:
        """POST with title of exactly 500 chars is accepted."""
        client, _, token = authed
        resp = await client.post(
            "/v1/entries",
            json={"title": "x" * 500, "content_format": "markdown"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        assert len(resp.json()["title"]) == 500

    async def test_create_entry_content_too_long(self, authed: AuthedFixture) -> None:
        """POST with content > 100k chars returns 422."""
        client, _, token = authed
        resp = await client.post(
            "/v1/entries",
            json={
                "title": "Huge Content",
                "content_format": "markdown",
                "content": "x" * 100_001,
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    async def test_create_entry_content_at_limit(self, authed: AuthedFixture) -> None:
        """POST with content of exactly 100k chars is accepted."""
        client, _, token = authed
        resp = await client.post(
            "/v1/entries",
            json={
                "title": "Max Content",
                "content_format": "markdown",
                "content": "x" * 100_000,
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 201


class TestCreateEntryIdempotency:
    """Scenario: Multiple creations produce distinct, independent entries."""

    async def test_create_multiple_entries_independent_ids(
        self, authed: AuthedFixture
    ) -> None:
        """Creating several entries gives each a unique id and repo_name."""
        client, _, token = authed
        headers = auth_header(token)
        ids = set()
        repo_names = set()
        for i in range(5):
            resp = await client.post(
                "/v1/entries",
                json={"title": f"Independent Entry {i}"},
                headers=headers,
            )
            assert resp.status_code == 201
            data = resp.json()
            ids.add(data["id"])
            repo_names.add(data["repo_name"])
        assert len(ids) == 5
        assert len(repo_names) == 5
