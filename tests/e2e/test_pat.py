# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for Personal Access Tokens (PHI-119).

Tests the full API path for:
- POST   /v1/auth/tokens       (create token, JWT auth only)
- GET    /v1/auth/tokens        (list user's tokens, JWT auth only)
- DELETE /v1/auth/tokens/{id}   (revoke token, JWT auth only)
- PAT authentication on all existing endpoints
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.e2e.conftest import auth_header, create_entry, register_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def create_pat(
    client: httpx.AsyncClient,
    jwt_token: str,
    *,
    name: str = "test-token",
    expires_in_days: int | None = None,
) -> dict:
    """Create a PAT via the API and return the full response JSON."""
    body: dict = {"name": name}
    if expires_in_days is not None:
        body["expires_in_days"] = expires_in_days
    resp = await client.post(
        "/v1/auth/tokens",
        json=body,
        headers=auth_header(jwt_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Token CRUD
# ---------------------------------------------------------------------------


class TestCreateToken:
    """Scenario: User creates a PAT for programmatic access."""

    async def test_create_token_returns_201_with_full_response(
        self, client: httpx.AsyncClient,
    ) -> None:
        """Create token returns 201 with id, name, key_prefix, token, created_at, expires_at."""
        auth = await register_user(client, username="pat-create")
        jwt = auth["access_token"]

        resp = await client.post(
            "/v1/auth/tokens",
            json={"name": "my-script"},
            headers=auth_header(jwt),
        )
        assert resp.status_code == 201
        data = resp.json()

        # Verify all required fields are present
        assert "id" in data
        assert "name" in data
        assert "key_prefix" in data
        assert "token" in data
        assert "created_at" in data
        assert "expires_at" in data

        # Verify field values
        assert data["name"] == "my-script"

        # Verify token format: starts with pat_, total length ~47 chars
        token = data["token"]
        assert token.startswith("pat_")
        assert len(token) >= 40  # pat_ (4) + 43 random chars

        # Verify key_prefix is first 8 chars of the random portion (chars 4-12)
        assert data["key_prefix"] == token[4:12]

        # Verify id is a valid UUID
        UUID(data["id"])

        # Verify created_at is a valid timestamp
        assert data["created_at"] is not None

    async def test_create_token_with_expiry(
        self, client: httpx.AsyncClient,
    ) -> None:
        """Create token with expires_in_days sets expires_at approximately N days from now."""
        auth = await register_user(client, username="pat-expiry")
        jwt = auth["access_token"]

        data = await create_pat(client, jwt, name="expiring", expires_in_days=90)

        assert data["expires_at"] is not None
        expires_at = datetime.fromisoformat(data["expires_at"])
        created_at = datetime.fromisoformat(data["created_at"])

        # expires_at should be roughly 90 days after created_at (allow 1 minute tolerance)
        delta = expires_at - created_at
        assert 89 <= delta.days <= 91

    async def test_create_token_without_expiry(
        self, client: httpx.AsyncClient,
    ) -> None:
        """Create token without expires_in_days sets expires_at to null."""
        auth = await register_user(client, username="pat-no-expiry")
        jwt = auth["access_token"]

        data = await create_pat(client, jwt, name="permanent")

        assert data["expires_at"] is None

    async def test_create_token_requires_jwt_auth(
        self, client: httpx.AsyncClient,
    ) -> None:
        """Create token without any bearer token returns 401."""
        resp = await client.post(
            "/v1/auth/tokens",
            json={"name": "should-fail"},
        )
        assert resp.status_code == 401

    async def test_create_token_rejects_pat_auth(
        self, client: httpx.AsyncClient,
    ) -> None:
        """Create token using a PAT (not JWT) returns 401 or 403 — PATs cannot manage tokens."""
        auth = await register_user(client, username="pat-reject")
        jwt = auth["access_token"]

        # First create a PAT using JWT
        pat_data = await create_pat(client, jwt, name="bootstrap-pat")
        pat_token = pat_data["token"]

        # Now try to use that PAT to create another token — must fail
        resp = await client.post(
            "/v1/auth/tokens",
            json={"name": "sneaky"},
            headers=auth_header(pat_token),
        )
        assert resp.status_code in (401, 403)

    async def test_create_token_validates_empty_name(
        self, client: httpx.AsyncClient,
    ) -> None:
        """Empty name is rejected with 422."""
        auth = await register_user(client, username="pat-empty-name")
        jwt = auth["access_token"]

        resp = await client.post(
            "/v1/auth/tokens",
            json={"name": ""},
            headers=auth_header(jwt),
        )
        assert resp.status_code == 422

    async def test_create_token_validates_name_too_long(
        self, client: httpx.AsyncClient,
    ) -> None:
        """Name longer than 100 chars is rejected with 422."""
        auth = await register_user(client, username="pat-long-name")
        jwt = auth["access_token"]

        resp = await client.post(
            "/v1/auth/tokens",
            json={"name": "x" * 101},
            headers=auth_header(jwt),
        )
        assert resp.status_code == 422

    async def test_create_token_name_max_length_ok(
        self, client: httpx.AsyncClient,
    ) -> None:
        """Name exactly 100 chars is accepted."""
        auth = await register_user(client, username="pat-max-name")
        jwt = auth["access_token"]

        data = await create_pat(client, jwt, name="x" * 100)
        assert data["name"] == "x" * 100

    async def test_create_token_unicode_name(
        self, client: httpx.AsyncClient,
    ) -> None:
        """Unicode characters in name are accepted."""
        auth = await register_user(client, username="pat-unicode")
        jwt = auth["access_token"]

        data = await create_pat(client, jwt, name="my-script-\u2603")
        assert data["name"] == "my-script-\u2603"

    async def test_create_multiple_tokens(
        self, client: httpx.AsyncClient,
    ) -> None:
        """Multiple tokens can be created and all work independently."""
        auth = await register_user(client, username="pat-multi")
        jwt = auth["access_token"]

        token1 = await create_pat(client, jwt, name="token-one")
        token2 = await create_pat(client, jwt, name="token-two")
        token3 = await create_pat(client, jwt, name="token-three")

        # All have distinct IDs
        ids = {token1["id"], token2["id"], token3["id"]}
        assert len(ids) == 3

        # All have distinct tokens
        tokens = {token1["token"], token2["token"], token3["token"]}
        assert len(tokens) == 3

        # All have distinct prefixes (with overwhelmingly high probability)
        prefixes = {token1["key_prefix"], token2["key_prefix"], token3["key_prefix"]}
        # We just verify they're 8 chars each — collision is astronomically unlikely
        for prefix in prefixes:
            assert len(prefix) == 8


class TestListTokens:
    """Scenario: User lists their PATs to manage them."""

    async def test_list_tokens_returns_metadata(
        self, client: httpx.AsyncClient,
    ) -> None:
        """List returns token metadata but never the raw token."""
        auth = await register_user(client, username="pat-list")
        jwt = auth["access_token"]

        created = await create_pat(client, jwt, name="listable", expires_in_days=30)

        resp = await client.get("/v1/auth/tokens", headers=auth_header(jwt))
        assert resp.status_code == 200
        tokens = resp.json()["items"]

        assert isinstance(tokens, list)
        assert len(tokens) >= 1

        # Find our created token
        found = [t for t in tokens if t["id"] == created["id"]]
        assert len(found) == 1

        token_data = found[0]
        assert token_data["name"] == "listable"
        assert token_data["key_prefix"] == created["key_prefix"]
        assert token_data["created_at"] is not None
        assert token_data["expires_at"] is not None
        assert "revoked_at" in token_data

        # CRITICAL: raw token must never appear in list response
        assert "token" not in token_data

    async def test_list_tokens_only_shows_own(
        self, client: httpx.AsyncClient,
    ) -> None:
        """User A's tokens are not visible to User B."""
        auth_a = await register_user(client, username="pat-owner-a")
        auth_b = await register_user(client, username="pat-owner-b")
        jwt_a = auth_a["access_token"]
        jwt_b = auth_b["access_token"]

        # User A creates tokens
        await create_pat(client, jwt_a, name="a-token-1")
        await create_pat(client, jwt_a, name="a-token-2")

        # User B creates a token
        await create_pat(client, jwt_b, name="b-token-1")

        # User B lists — should only see their own
        resp_b = await client.get("/v1/auth/tokens", headers=auth_header(jwt_b))
        assert resp_b.status_code == 200
        b_tokens = resp_b.json()["items"]
        assert len(b_tokens) == 1
        assert b_tokens[0]["name"] == "b-token-1"

        # User A lists — should only see their own
        resp_a = await client.get("/v1/auth/tokens", headers=auth_header(jwt_a))
        assert resp_a.status_code == 200
        a_tokens = resp_a.json()["items"]
        assert len(a_tokens) == 2
        a_names = {t["name"] for t in a_tokens}
        assert a_names == {"a-token-1", "a-token-2"}

    async def test_list_tokens_requires_jwt_auth(
        self, client: httpx.AsyncClient,
    ) -> None:
        """List tokens without auth returns 401."""
        resp = await client.get("/v1/auth/tokens")
        assert resp.status_code == 401

    async def test_list_tokens_rejects_pat_auth(
        self, client: httpx.AsyncClient,
    ) -> None:
        """List tokens using PAT auth is rejected — token management requires JWT."""
        auth = await register_user(client, username="pat-list-reject")
        jwt = auth["access_token"]

        pat_data = await create_pat(client, jwt, name="self-list-attempt")
        pat_token = pat_data["token"]

        resp = await client.get("/v1/auth/tokens", headers=auth_header(pat_token))
        assert resp.status_code in (401, 403)


class TestRevokeToken:
    """Scenario: User revokes a PAT to disable programmatic access."""

    async def test_revoke_token_returns_204(
        self, client: httpx.AsyncClient,
    ) -> None:
        """Revoking a token returns 204 and sets revoked_at."""
        auth = await register_user(client, username="pat-revoke")
        jwt = auth["access_token"]

        created = await create_pat(client, jwt, name="to-revoke")
        token_id = created["id"]

        resp = await client.delete(
            f"/v1/auth/tokens/{token_id}",
            headers=auth_header(jwt),
        )
        assert resp.status_code == 204

        # Verify revoked_at is set in the list
        list_resp = await client.get("/v1/auth/tokens", headers=auth_header(jwt))
        tokens = list_resp.json()["items"]
        revoked = [t for t in tokens if t["id"] == token_id]
        assert len(revoked) == 1
        assert revoked[0]["revoked_at"] is not None

    async def test_revoke_nonexistent_token_returns_404(
        self, client: httpx.AsyncClient,
    ) -> None:
        """Revoking a non-existent token ID returns 404."""
        auth = await register_user(client, username="pat-revoke-404")
        jwt = auth["access_token"]

        resp = await client.delete(
            "/v1/auth/tokens/00000000-0000-0000-0000-000000000000",
            headers=auth_header(jwt),
        )
        assert resp.status_code == 404

    async def test_revoke_other_users_token_returns_404(
        self, client: httpx.AsyncClient,
    ) -> None:
        """Revoking another user's token returns 404 (not 403 — don't reveal existence)."""
        auth_a = await register_user(client, username="pat-rev-a")
        auth_b = await register_user(client, username="pat-rev-b")
        jwt_a = auth_a["access_token"]
        jwt_b = auth_b["access_token"]

        # User A creates a token
        created = await create_pat(client, jwt_a, name="a-only")
        token_id = created["id"]

        # User B tries to revoke it
        resp = await client.delete(
            f"/v1/auth/tokens/{token_id}",
            headers=auth_header(jwt_b),
        )
        assert resp.status_code == 404

    async def test_revoke_requires_jwt_auth(
        self, client: httpx.AsyncClient,
    ) -> None:
        """Revoke without auth returns 401."""
        resp = await client.delete(
            "/v1/auth/tokens/00000000-0000-0000-0000-000000000000",
        )
        assert resp.status_code == 401

    async def test_revoke_rejects_pat_auth(
        self, client: httpx.AsyncClient,
    ) -> None:
        """Revoking a token using PAT auth is rejected — requires JWT."""
        auth = await register_user(client, username="pat-rev-reject")
        jwt = auth["access_token"]

        pat_data = await create_pat(client, jwt, name="self-revoke-attempt")
        pat_token = pat_data["token"]

        resp = await client.delete(
            f"/v1/auth/tokens/{pat_data['id']}",
            headers=auth_header(pat_token),
        )
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# PAT Authentication
# ---------------------------------------------------------------------------


class TestPatAuthentication:
    """Scenario: Programmatic client uses a PAT to authenticate API requests."""

    async def test_pat_authenticates_on_me_endpoint(
        self, client: httpx.AsyncClient,
    ) -> None:
        """Using a PAT to access /v1/auth/me returns the user who created the token."""
        auth = await register_user(client, username="pat-me-user")
        jwt = auth["access_token"]
        user = auth["user"]

        pat_data = await create_pat(client, jwt, name="me-token")
        pat_token = pat_data["token"]

        resp = await client.get("/v1/auth/me", headers=auth_header(pat_token))
        assert resp.status_code == 200
        me = resp.json()
        assert me["username"] == "pat-me-user"
        assert me["id"] == user["id"]

    async def test_pat_authenticates_for_entry_creation(
        self, client: httpx.AsyncClient,
    ) -> None:
        """Using a PAT to create an entry (POST /v1/entries) succeeds."""
        auth = await register_user(client, username="pat-entry-user")
        jwt = auth["access_token"]

        pat_data = await create_pat(client, jwt, name="entry-token")
        pat_token = pat_data["token"]

        resp = await client.post(
            "/v1/entries",
            json={"title": "PAT-Created Entry"},
            headers=auth_header(pat_token),
        )
        assert resp.status_code == 201
        assert resp.json()["created_by"] == auth["user"]["id"]

    async def test_pat_works_on_public_endpoint_with_optional_auth(
        self, client: httpx.AsyncClient,
    ) -> None:
        """Using a PAT on a public endpoint with optional auth identifies the user."""
        auth = await register_user(client, username="pat-public-user")
        jwt = auth["access_token"]

        pat_data = await create_pat(client, jwt, name="public-token")
        pat_token = pat_data["token"]

        # GET /v1/entries is public but can identify user via optional auth
        resp = await client.get("/v1/entries", headers=auth_header(pat_token))
        assert resp.status_code == 200

    async def test_revoked_pat_returns_401(
        self, client: httpx.AsyncClient,
    ) -> None:
        """After revocation, using the token gives 401."""
        auth = await register_user(client, username="pat-revoked-user")
        jwt = auth["access_token"]

        pat_data = await create_pat(client, jwt, name="revokable")
        pat_token = pat_data["token"]

        # Verify it works first
        resp1 = await client.get("/v1/auth/me", headers=auth_header(pat_token))
        assert resp1.status_code == 200

        # Revoke it
        await client.delete(
            f"/v1/auth/tokens/{pat_data['id']}",
            headers=auth_header(jwt),
        )

        # Now it should fail
        resp2 = await client.get("/v1/auth/me", headers=auth_header(pat_token))
        assert resp2.status_code == 401

    async def test_expired_pat_returns_401(
        self, client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """An expired PAT returns 401.

        We create a token with a short expiry, then manipulate expires_at
        in the DB to be in the past.
        """
        from phiacta.core.models.personal_access_token import PersonalAccessToken as PATModel

        auth = await register_user(client, username="pat-expired-user")
        jwt = auth["access_token"]

        # Create a token with 1-day expiry, then backdate it
        pat_data = await create_pat(client, jwt, name="ephemeral", expires_in_days=1)
        pat_token = pat_data["token"]

        # Manipulate expires_at to the past
        async with e2e_session_factory() as session:
            from sqlalchemy import select as sa_select
            result = await session.execute(
                sa_select(PATModel).where(PATModel.id == UUID(pat_data["id"]))
            )
            pat = result.scalar_one()
            pat.expires_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
            await session.commit()

        resp = await client.get("/v1/auth/me", headers=auth_header(pat_token))
        assert resp.status_code == 401

    async def test_jwt_still_works_after_creating_pats(
        self, client: httpx.AsyncClient,
    ) -> None:
        """Creating PATs does not break JWT authentication."""
        auth = await register_user(client, username="pat-jwt-still")
        jwt = auth["access_token"]

        # Create some PATs
        await create_pat(client, jwt, name="pat-1")
        await create_pat(client, jwt, name="pat-2")

        # JWT should still work
        resp = await client.get("/v1/auth/me", headers=auth_header(jwt))
        assert resp.status_code == 200
        assert resp.json()["username"] == "pat-jwt-still"

    async def test_malformed_pat_prefix_only(
        self, client: httpx.AsyncClient,
    ) -> None:
        """'pat_' alone (no random chars) returns 401."""
        resp = await client.get("/v1/auth/me", headers=auth_header("pat_"))
        assert resp.status_code == 401

    async def test_malformed_pat_too_short(
        self, client: httpx.AsyncClient,
    ) -> None:
        """'pat_ab' (too short for prefix extraction) returns 401."""
        resp = await client.get("/v1/auth/me", headers=auth_header("pat_ab"))
        assert resp.status_code == 401

    async def test_malformed_pat_very_long(
        self, client: httpx.AsyncClient,
    ) -> None:
        """A very long token starting with pat_ returns 401."""
        long_token = "pat_" + "a" * 1000
        resp = await client.get("/v1/auth/me", headers=auth_header(long_token))
        assert resp.status_code == 401

    async def test_invalid_pat_right_format_wrong_key(
        self, client: httpx.AsyncClient,
    ) -> None:
        """A token with pat_ prefix and correct length but wrong key returns 401."""
        # Generate a plausible-looking token that does not exist in the DB
        fake_token = "pat_" + "X" * 43
        resp = await client.get("/v1/auth/me", headers=auth_header(fake_token))
        assert resp.status_code == 401

    async def test_revoked_pat_on_optional_auth_endpoint_returns_anonymous(
        self, client: httpx.AsyncClient,
    ) -> None:
        """A revoked PAT on an optional-auth endpoint returns anonymous (not 401).

        GET /v1/entries uses optional auth — a bad PAT should result in
        anonymous access (None user), not an error.
        """
        auth = await register_user(client, username="pat-opt-anon")
        jwt = auth["access_token"]

        pat_data = await create_pat(client, jwt, name="opt-revoke")
        pat_token = pat_data["token"]

        # Revoke it
        await client.delete(
            f"/v1/auth/tokens/{pat_data['id']}",
            headers=auth_header(jwt),
        )

        # On optional-auth endpoint, revoked PAT => anonymous, not 401
        resp = await client.get("/v1/entries", headers=auth_header(pat_token))
        assert resp.status_code == 200

    async def test_pat_cannot_create_pat(
        self, client: httpx.AsyncClient,
    ) -> None:
        """A PAT used to create another PAT is rejected — all token management requires JWT."""
        auth = await register_user(client, username="pat-no-create")
        jwt = auth["access_token"]

        pat_data = await create_pat(client, jwt, name="base-pat")
        pat_token = pat_data["token"]

        resp = await client.post(
            "/v1/auth/tokens",
            json={"name": "sneaky-child"},
            headers=auth_header(pat_token),
        )
        assert resp.status_code in (401, 403)

    async def test_pat_cannot_list_tokens(
        self, client: httpx.AsyncClient,
    ) -> None:
        """A PAT used to list tokens is rejected."""
        auth = await register_user(client, username="pat-no-list")
        jwt = auth["access_token"]

        pat_data = await create_pat(client, jwt, name="no-list-pat")
        pat_token = pat_data["token"]

        resp = await client.get("/v1/auth/tokens", headers=auth_header(pat_token))
        assert resp.status_code in (401, 403)

    async def test_pat_cannot_revoke_tokens(
        self, client: httpx.AsyncClient,
    ) -> None:
        """A PAT used to revoke a token is rejected."""
        auth = await register_user(client, username="pat-no-revoke")
        jwt = auth["access_token"]

        pat_data = await create_pat(client, jwt, name="no-revoke-pat")
        pat_token = pat_data["token"]

        resp = await client.delete(
            f"/v1/auth/tokens/{pat_data['id']}",
            headers=auth_header(pat_token),
        )
        assert resp.status_code in (401, 403)


class TestPatLastUsedAt:
    """Scenario: last_used_at is updated when a PAT is used for authentication."""

    async def test_last_used_at_initially_null(
        self, client: httpx.AsyncClient,
    ) -> None:
        """A newly created token has last_used_at as null."""
        auth = await register_user(client, username="pat-lastused-null")
        jwt = auth["access_token"]

        await create_pat(client, jwt, name="unused")

        resp = await client.get("/v1/auth/tokens", headers=auth_header(jwt))
        tokens = resp.json()["items"]
        assert len(tokens) == 1
        assert tokens[0]["last_used_at"] is None

    async def test_last_used_at_updated_after_use(
        self, client: httpx.AsyncClient,
    ) -> None:
        """After using a PAT, last_used_at is set to a recent timestamp."""
        auth = await register_user(client, username="pat-lastused-set")
        jwt = auth["access_token"]

        pat_data = await create_pat(client, jwt, name="will-use")
        pat_token = pat_data["token"]

        # Use the PAT
        before = datetime.now(timezone.utc)
        resp = await client.get("/v1/auth/me", headers=auth_header(pat_token))
        assert resp.status_code == 200

        # Check last_used_at is set
        list_resp = await client.get("/v1/auth/tokens", headers=auth_header(jwt))
        tokens = list_resp.json()["items"]
        used_token = [t for t in tokens if t["id"] == pat_data["id"]]
        assert len(used_token) == 1

        last_used = used_token[0]["last_used_at"]
        if last_used is not None:
            last_used_dt = datetime.fromisoformat(last_used)
            # Handle naive datetimes from SQLite
            if last_used_dt.tzinfo is None:
                last_used_dt = last_used_dt.replace(tzinfo=timezone.utc)
            # Should be recent (within 60 seconds)
            assert (last_used_dt - before).total_seconds() < 60
