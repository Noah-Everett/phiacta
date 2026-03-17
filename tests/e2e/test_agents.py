# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for agent public profile endpoint (NEV-121).

Tests the full API contract for:
- GET /v1/agents/{agent_id}  — public profile, no auth required
"""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from tests.e2e.conftest import register_agent


# ---------------------------------------------------------------------------
# GET /v1/agents/{agent_id} — Public profile
# ---------------------------------------------------------------------------


class TestGetAgentProfile:
    """Scenario: Getting a public agent profile returns correct fields."""

    async def test_get_agent_returns_public_profile(
        self, client: httpx.AsyncClient
    ) -> None:
        """Returns id, handle, agent_type, is_active, created_at."""
        auth = await register_agent(
            client, handle="profile-agent", email="profile@example.com"
        )
        agent_id = auth["agent"]["id"]

        resp = await client.get(f"/v1/agents/{agent_id}")
        assert resp.status_code == 200
        data = resp.json()

        assert data["id"] == agent_id
        assert data["handle"] == "profile-agent"
        assert data["agent_type"] == "human"
        assert data["is_active"] is True
        assert data["created_at"] is not None

    async def test_get_agent_does_not_require_authentication(
        self, client: httpx.AsyncClient
    ) -> None:
        """GET /v1/agents/{id} is public, no auth header needed."""
        auth = await register_agent(
            client, handle="public-agent", email="public@example.com"
        )
        agent_id = auth["agent"]["id"]

        # No Authorization header
        resp = await client.get(f"/v1/agents/{agent_id}")
        assert resp.status_code == 200

    async def test_response_excludes_email(
        self, client: httpx.AsyncClient
    ) -> None:
        """Email must NOT be in the public response."""
        auth = await register_agent(
            client, handle="no-email-agent", email="secret@example.com"
        )
        agent_id = auth["agent"]["id"]

        resp = await client.get(f"/v1/agents/{agent_id}")
        assert resp.status_code == 200
        assert "email" not in resp.json()

    async def test_response_excludes_password_hash(
        self, client: httpx.AsyncClient
    ) -> None:
        """password_hash must NOT be in the public response."""
        auth = await register_agent(
            client, handle="no-pw-agent", email="nopw@example.com"
        )
        agent_id = auth["agent"]["id"]

        resp = await client.get(f"/v1/agents/{agent_id}")
        assert resp.status_code == 200
        assert "password_hash" not in resp.json()

    async def test_response_has_exactly_expected_fields(
        self, client: httpx.AsyncClient
    ) -> None:
        """Response has exactly {id, handle, agent_type, is_active, created_at}."""
        auth = await register_agent(
            client, handle="exact-fields", email="exact@example.com"
        )
        agent_id = auth["agent"]["id"]

        resp = await client.get(f"/v1/agents/{agent_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == {
            "id", "handle", "agent_type", "is_active", "created_at",
        }


class TestGetAgentProfileErrors:
    """Scenario: Error responses for the agent profile endpoint."""

    async def test_nonexistent_uuid_returns_404(
        self, client: httpx.AsyncClient
    ) -> None:
        """GET with a valid UUID that does not exist returns 404."""
        resp = await client.get(f"/v1/agents/{uuid4()}")
        assert resp.status_code == 404

    async def test_invalid_uuid_format_returns_422(
        self, client: httpx.AsyncClient
    ) -> None:
        """GET with an invalid UUID format returns 422."""
        resp = await client.get("/v1/agents/not-a-valid-uuid")
        assert resp.status_code == 422

    async def test_numeric_id_returns_422(
        self, client: httpx.AsyncClient
    ) -> None:
        """GET with a plain number instead of UUID returns 422."""
        resp = await client.get("/v1/agents/12345")
        assert resp.status_code == 422


class TestGetAgentProfileFieldValues:
    """Scenario: Field values are correct for different agent states."""

    async def test_is_active_true_for_new_agent(
        self, client: httpx.AsyncClient
    ) -> None:
        """Newly registered agent has is_active=true."""
        auth = await register_agent(
            client, handle="active-check", email="active@example.com"
        )
        agent_id = auth["agent"]["id"]

        resp = await client.get(f"/v1/agents/{agent_id}")
        assert resp.status_code == 200
        assert resp.json()["is_active"] is True

    async def test_agent_type_is_human_for_registered_agent(
        self, client: httpx.AsyncClient
    ) -> None:
        """Registered agents have agent_type='human'."""
        auth = await register_agent(
            client, handle="type-check", email="type@example.com"
        )
        agent_id = auth["agent"]["id"]

        resp = await client.get(f"/v1/agents/{agent_id}")
        assert resp.status_code == 200
        assert resp.json()["agent_type"] == "human"
