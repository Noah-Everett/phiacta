# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E smoke tests for health and basic routing."""

from __future__ import annotations

from uuid import uuid4

import httpx


class TestHealth:
    async def test_health(self, client: httpx.AsyncClient) -> None:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "healthy"}


class TestSmoke:
    async def test_nonexistent_user_returns_404(self, client: httpx.AsyncClient) -> None:
        """A GET to a non-existent user returns 404, not 500."""
        resp = await client.get(f"/v1/users/{uuid4()}")
        assert resp.status_code == 404

    async def test_nonexistent_route_returns_404(self, client: httpx.AsyncClient) -> None:
        """A GET to a completely unknown route returns 404."""
        resp = await client.get("/v1/does-not-exist")
        assert resp.status_code == 404
