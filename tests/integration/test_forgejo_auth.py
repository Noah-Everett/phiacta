# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Integration tests for auth and users against real Postgres.

These tests require the Docker stack to be running:
    docker compose up -d

Run with:
    pytest tests/integration/test_forgejo_auth.py -m forgejo
"""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

BASE_URL = "http://localhost:8000"

pytestmark = [pytest.mark.forgejo, pytest.mark.anyio]


def _unique_user() -> dict[str, str]:
    """Return a unique RegisterRequest payload."""
    uid = uuid4().hex[:12]
    return {
        "username": f"test_{uid}",
        "password": "S3cur3P@ssword!",
    }


# ---------------------------------------------------------------------------
# Registration + login
# ---------------------------------------------------------------------------


async def test_register_and_login() -> None:
    """Register, login, verify /auth/me returns correct user data."""
    payload = _unique_user()

    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        resp = await client.post("/v1/auth/register", json=payload)
        assert resp.status_code == 201, resp.text

        reg_body = resp.json()
        assert "access_token" in reg_body
        assert reg_body["token_type"] == "bearer"
        user_data = reg_body["user"]
        assert user_data["username"] == payload["username"]

        reg_token = reg_body["access_token"]

        login_resp = await client.post(
            "/v1/auth/login",
            json={"username": payload["username"], "password": payload["password"]},
        )
        assert login_resp.status_code == 200, login_resp.text
        login_body = login_resp.json()
        assert "access_token" in login_body
        assert login_body["user"]["username"] == payload["username"]

        me_resp = await client.get(
            "/v1/auth/me",
            headers={"Authorization": f"Bearer {reg_token}"},
        )
        assert me_resp.status_code == 200, me_resp.text
        me_body = me_resp.json()
        assert me_body["username"] == payload["username"]
        assert me_body["id"] == user_data["id"]


async def test_register_duplicate_username_rejected() -> None:
    """Same username rejected on second registration."""
    payload = _unique_user()

    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        resp = await client.post("/v1/auth/register", json=payload)
        assert resp.status_code == 201

        duplicate = {
            "username": payload["username"],
            "password": payload["password"],
        }
        dup_resp = await client.post("/v1/auth/register", json=duplicate)
        assert dup_resp.status_code in (409, 422), dup_resp.text


# ---------------------------------------------------------------------------
# Login failure cases
# ---------------------------------------------------------------------------


async def test_login_wrong_password() -> None:
    """Wrong password returns 401."""
    payload = _unique_user()

    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        await client.post("/v1/auth/register", json=payload)

        resp = await client.post(
            "/v1/auth/login",
            json={"username": payload["username"], "password": "Wr0ngP@ssword!"},
        )
        assert resp.status_code == 401


async def test_login_nonexistent_username() -> None:
    """Nonexistent username returns 401."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        resp = await client.post(
            "/v1/auth/login",
            json={
                "username": f"ghost_{uuid4().hex}",
                "password": "S3cur3P@ssword!",
            },
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /auth/me token validation
# ---------------------------------------------------------------------------


async def test_me_without_token() -> None:
    """No Authorization header returns 401."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        resp = await client.get("/v1/auth/me")
        assert resp.status_code == 401


async def test_me_with_invalid_token() -> None:
    """Garbage JWT returns 401."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        resp = await client.get(
            "/v1/auth/me",
            headers={"Authorization": "Bearer this.is.not.a.valid.jwt"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# User public profile
# ---------------------------------------------------------------------------


async def test_get_user_by_id() -> None:
    """GET /users/{id} returns public profile."""
    payload = _unique_user()

    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        reg = await client.post("/v1/auth/register", json=payload)
        assert reg.status_code == 201

        user_id = reg.json()["user"]["id"]
        profile_resp = await client.get(f"/v1/users/{user_id}")
        assert profile_resp.status_code == 200

        profile = profile_resp.json()
        assert profile["id"] == user_id
        assert profile["username"] == payload["username"]


async def test_get_nonexistent_user() -> None:
    """Random UUID returns 404."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        resp = await client.get(f"/v1/users/{uuid4()}")
        assert resp.status_code == 404
