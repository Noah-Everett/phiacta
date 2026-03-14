# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for authentication endpoints."""

from __future__ import annotations

import httpx

from tests.e2e.conftest import auth_header, register_agent


class TestRegister:
    async def test_register_success(self, client: httpx.AsyncClient) -> None:
        resp = await client.post("/v1/auth/register", json={
            "handle": "alice",
            "email": "alice@example.com",
            "password": "SecurePass123!",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["agent"]["handle"] == "alice"
        assert data["agent"]["agent_type"] == "human"
        assert data["agent"]["is_active"] is True

    async def test_register_duplicate_email(self, client: httpx.AsyncClient) -> None:
        await register_agent(client, handle="first", email="dup@example.com")
        resp = await client.post("/v1/auth/register", json={
            "handle": "second",
            "email": "dup@example.com",
            "password": "SecurePass123!",
        })
        assert resp.status_code == 409
        assert "Email already registered" in resp.json()["detail"]

    async def test_register_duplicate_handle(self, client: httpx.AsyncClient) -> None:
        await register_agent(client, handle="taken", email="first@example.com")
        resp = await client.post("/v1/auth/register", json={
            "handle": "taken",
            "email": "second@example.com",
            "password": "SecurePass123!",
        })
        assert resp.status_code == 409
        assert "Handle already taken" in resp.json()["detail"]

    async def test_register_short_password(self, client: httpx.AsyncClient) -> None:
        resp = await client.post("/v1/auth/register", json={
            "handle": "bob",
            "email": "bob@example.com",
            "password": "short",
        })
        assert resp.status_code == 422

    async def test_register_invalid_email(self, client: httpx.AsyncClient) -> None:
        resp = await client.post("/v1/auth/register", json={
            "handle": "bob",
            "email": "not-an-email",
            "password": "SecurePass123!",
        })
        assert resp.status_code == 422

    async def test_register_empty_handle(self, client: httpx.AsyncClient) -> None:
        resp = await client.post("/v1/auth/register", json={
            "handle": "",
            "email": "bob@example.com",
            "password": "SecurePass123!",
        })
        assert resp.status_code == 422


class TestLogin:
    async def test_login_success(self, client: httpx.AsyncClient) -> None:
        await register_agent(client, email="login@example.com", password="MyPassword123!")
        resp = await client.post("/v1/auth/login", json={
            "email": "login@example.com",
            "password": "MyPassword123!",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["agent"]["handle"] == "test-agent"

    async def test_login_wrong_password(self, client: httpx.AsyncClient) -> None:
        await register_agent(client, email="wrong@example.com", password="CorrectPass123!")
        resp = await client.post("/v1/auth/login", json={
            "email": "wrong@example.com",
            "password": "WrongPassword123!",
        })
        assert resp.status_code == 401
        assert "Invalid email or password" in resp.json()["detail"]

    async def test_login_nonexistent_email(self, client: httpx.AsyncClient) -> None:
        resp = await client.post("/v1/auth/login", json={
            "email": "nobody@example.com",
            "password": "DoesNotMatter123!",
        })
        assert resp.status_code == 401
        assert "Invalid email or password" in resp.json()["detail"]


class TestMe:
    async def test_me_authenticated(self, client: httpx.AsyncClient) -> None:
        auth = await register_agent(client, handle="me-test", email="me@example.com")
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
