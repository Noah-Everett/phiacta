# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for user public profile endpoint.

Tests the full API contract for:
- GET /v1/users/{user_id}  — public profile, no auth required
"""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from tests.e2e.conftest import register_user


# ---------------------------------------------------------------------------
# GET /v1/users/{user_id} — Public profile
# ---------------------------------------------------------------------------


class TestGetUserProfile:
    """Scenario: Getting a public user profile returns correct fields."""

    async def test_get_user_returns_public_profile(
        self, client: httpx.AsyncClient
    ) -> None:
        """Returns id, username, created_at."""
        auth = await register_user(client, username="profile-user")
        user_id = auth["user"]["id"]

        resp = await client.get(f"/v1/users/{user_id}")
        assert resp.status_code == 200
        data = resp.json()

        assert data["id"] == user_id
        assert data["username"] == "profile-user"
        assert data["created_at"] is not None

    async def test_get_user_does_not_require_authentication(
        self, client: httpx.AsyncClient
    ) -> None:
        """GET /v1/users/{id} is public, no auth header needed."""
        auth = await register_user(client, username="public-user")
        user_id = auth["user"]["id"]

        # No Authorization header
        resp = await client.get(f"/v1/users/{user_id}")
        assert resp.status_code == 200

    async def test_response_excludes_password_hash(
        self, client: httpx.AsyncClient
    ) -> None:
        """password_hash must NOT be in the public response."""
        auth = await register_user(client, username="no-pw-user")
        user_id = auth["user"]["id"]

        resp = await client.get(f"/v1/users/{user_id}")
        assert resp.status_code == 200
        assert "password_hash" not in resp.json()

    async def test_response_has_exactly_expected_fields(
        self, client: httpx.AsyncClient
    ) -> None:
        """Response has exactly {id, username, created_at}."""
        auth = await register_user(client, username="exact-fields")
        user_id = auth["user"]["id"]

        resp = await client.get(f"/v1/users/{user_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == {"id", "username", "created_at"}


class TestGetUserProfileErrors:
    """Scenario: Error responses for the user profile endpoint."""

    async def test_nonexistent_uuid_returns_404(
        self, client: httpx.AsyncClient
    ) -> None:
        """GET with a valid UUID that does not exist returns 404."""
        resp = await client.get(f"/v1/users/{uuid4()}")
        assert resp.status_code == 404

    async def test_invalid_uuid_format_returns_422(
        self, client: httpx.AsyncClient
    ) -> None:
        """GET with an invalid UUID format returns 422."""
        resp = await client.get("/v1/users/not-a-valid-uuid")
        assert resp.status_code == 422

    async def test_numeric_id_returns_422(
        self, client: httpx.AsyncClient
    ) -> None:
        """GET with a plain number instead of UUID returns 422."""
        resp = await client.get("/v1/users/12345")
        assert resp.status_code == 422
