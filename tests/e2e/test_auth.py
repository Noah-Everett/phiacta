# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for authentication endpoints."""

from __future__ import annotations

import httpx

from tests.e2e.conftest import auth_header, register_user


class TestRegister:
    async def test_register_success(self, client: httpx.AsyncClient) -> None:
        resp = await client.post("/v1/auth/register", json={
            "handle": "alice",
            "password": "SecurePass123!",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["handle"] == "alice"

    async def test_register_duplicate_handle(self, client: httpx.AsyncClient) -> None:
        await register_user(client, handle="taken")
        resp = await client.post("/v1/auth/register", json={
            "handle": "taken",
            "password": "SecurePass123!",
        })
        assert resp.status_code == 409
        assert "Handle already taken" in resp.json()["detail"]

    async def test_register_short_password(self, client: httpx.AsyncClient) -> None:
        resp = await client.post("/v1/auth/register", json={
            "handle": "bob",
            "password": "short",
        })
        assert resp.status_code == 422

    async def test_register_empty_handle(self, client: httpx.AsyncClient) -> None:
        resp = await client.post("/v1/auth/register", json={
            "handle": "",
            "password": "SecurePass123!",
        })
        assert resp.status_code == 422


class TestLogin:
    async def test_login_success(self, client: httpx.AsyncClient) -> None:
        await register_user(client, handle="login-user", password="MyPassword123!")
        resp = await client.post("/v1/auth/login", json={
            "handle": "login-user",
            "password": "MyPassword123!",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["user"]["handle"] == "login-user"

    async def test_login_wrong_password(self, client: httpx.AsyncClient) -> None:
        await register_user(client, handle="wrong-pw", password="CorrectPass123!")
        resp = await client.post("/v1/auth/login", json={
            "handle": "wrong-pw",
            "password": "WrongPassword123!",
        })
        assert resp.status_code == 401
        assert "Invalid handle or password" in resp.json()["detail"]

    async def test_login_nonexistent_handle(self, client: httpx.AsyncClient) -> None:
        resp = await client.post("/v1/auth/login", json={
            "handle": "nobody",
            "password": "DoesNotMatter123!",
        })
        assert resp.status_code == 401
        assert "Invalid handle or password" in resp.json()["detail"]


class TestMe:
    async def test_me_authenticated(self, client: httpx.AsyncClient) -> None:
        auth = await register_user(client, handle="me-test")
        token = auth["access_token"]
        resp = await client.get("/v1/auth/me", headers=auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["handle"] == "me-test"

    async def test_me_no_token(self, client: httpx.AsyncClient) -> None:
        resp = await client.get("/v1/auth/me")
        assert resp.status_code == 401

    async def test_me_invalid_token(self, client: httpx.AsyncClient) -> None:
        resp = await client.get("/v1/auth/me", headers=auth_header("garbage.token.here"))
        assert resp.status_code == 401
