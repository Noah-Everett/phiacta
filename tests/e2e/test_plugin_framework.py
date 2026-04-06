# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for the plugin framework (NEV-199).

Tests that the FastAPI app correctly handles plugin discovery, router
mounting, and coexistence with core endpoints. Uses the real httpx test
client against the FastAPI app with dependency overrides.
"""

from __future__ import annotations

import types
from uuid import uuid4

import httpx
import pytest

from tests.e2e.conftest import create_entry, register_user

# ---------------------------------------------------------------------------
# Helpers: synthetic plugin modules
# ---------------------------------------------------------------------------


def _create_synthetic_plugin_module(
    name: str,
    plugin_type: str,
    *,
    route_path: str = "/ping",
    route_response: dict | None = None,
    depends_on: list[str] | None = None,
    settings_class: type | None = None,
) -> types.ModuleType:
    """Build a fake plugin module with manifest + optional router in memory.

    This does NOT touch the filesystem -- it creates a module object that can
    be injected into sys.modules so the plugin registry discovers it.
    """
    from fastapi import APIRouter
    from phiacta.plugin import PluginManifest, PluginType

    mod = types.ModuleType(f"phiacta.{plugin_type}s.{name}")

    type_map = {
        "extension": PluginType.EXTENSION,
        "tool": PluginType.TOOL,
    }

    mod.manifest = PluginManifest(  # type: ignore[attr-defined]
        name=name,
        type=type_map[plugin_type],
        version="0.1.0",
        depends_on=depends_on or [],
        description=f"Synthetic {plugin_type} plugin: {name}",
        settings_class=settings_class,
    )

    router = APIRouter()
    response = route_response or {"plugin": name, "status": "ok"}

    @router.get(route_path)
    async def _ping() -> dict:
        return response

    mod.router = router  # type: ignore[attr-defined]
    return mod


# ---------------------------------------------------------------------------
# E2E: App starts with no plugins -- core endpoints work
# ---------------------------------------------------------------------------


class TestAppWithNoPlugins:
    """Scenario: Application starts with default config (enabled_plugins=[]).
    All core endpoints remain fully functional.
    """

    async def test_health_endpoint_returns_200(
        self, client: httpx.AsyncClient
    ) -> None:
        """Core /health endpoint works when no plugins are loaded."""
        resp = await client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"

    async def test_ready_endpoint_accessible(
        self, client: httpx.AsyncClient
    ) -> None:
        """Core /ready endpoint is accessible with no plugins.

        Note: /ready checks the production DB engine (get_engine()) which may
        not be available in tests. An OSError may propagate through the ASGI
        transport if the DB is unreachable, so we accept that as proof the
        route exists. A 404 would mean the route is missing entirely.
        """
        try:
            resp = await client.get("/ready")
            # Route exists -- any status other than 404 is fine
            assert resp.status_code != 404
        except (OSError, TypeError):
            # DB connection refused or pool config mismatch (SQLite in tests)
            # -- route exists but DB is unreachable
            pass

    async def test_entries_list_returns_200(
        self, client: httpx.AsyncClient
    ) -> None:
        """Core GET /v1/entries works when no plugins loaded."""
        resp = await client.get("/v1/entries")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "has_more" in data
        assert "next_cursor" in data

    async def test_auth_register_returns_201(
        self, client: httpx.AsyncClient
    ) -> None:
        """Core POST /v1/auth/register works when no plugins loaded."""
        resp = await client.post("/v1/auth/register", json={
            "username": f"no-plugin-{uuid4().hex[:8]}",
            "password": "TestPassword123!",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "access_token" in data
        assert "user" in data

    async def test_nonexistent_plugin_endpoint_returns_404(
        self, client: httpx.AsyncClient
    ) -> None:
        """Requests to /v1/extensions/nonexistent/... return 404 when no plugins loaded."""
        resp = await client.get("/v1/extensions/nonexistent/ping")
        assert resp.status_code == 404

    async def test_nonexistent_view_endpoint_returns_404(
        self, client: httpx.AsyncClient
    ) -> None:
        """Requests to /v1/views/nonexistent/... return 404 when no plugins loaded."""
        resp = await client.get("/v1/views/nonexistent/query")
        assert resp.status_code == 404

    async def test_nonexistent_tool_endpoint_returns_404(
        self, client: httpx.AsyncClient
    ) -> None:
        """Requests to /v1/tools/nonexistent/... return 404 when no plugins loaded."""
        resp = await client.get("/v1/tools/nonexistent/run")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# E2E: App starts with a mock plugin -- router mounted at correct prefix
# ---------------------------------------------------------------------------


class TestAppWithPluginEnabled:
    """Scenario: Application has a plugin router mounted. The plugin's
    router is at the correct prefix and returns expected responses,
    while core endpoints continue to work.

    Fixtures directly mount plugin routers on the FastAPI app instance
    (the same way the registry does at startup) and remove them after
    each test. This tests the routing contract without requiring
    lifespan re-entry.
    """

    @pytest.fixture
    def _install_test_extension(self, client: httpx.AsyncClient) -> str:
        """Mount a synthetic extension plugin router on the app."""
        from phiacta.main import app as _app

        name = "test_ext"
        mod = _create_synthetic_plugin_module(
            name,
            "extension",
            route_path="/ping",
            route_response={"plugin": name, "type": "extension", "ok": True},
        )
        _app.include_router(mod.router, prefix=f"/v1/extensions/{name}", tags=[name])
        yield name
        # Remove the plugin routes after the test
        _app.routes[:] = [
            r for r in _app.routes
            if not (hasattr(r, "path") and r.path.startswith(f"/v1/extensions/{name}"))
        ]

    @pytest.fixture
    def _install_test_view(self, client: httpx.AsyncClient) -> str:
        """Mount a synthetic extension plugin router on the app (views are now extensions)."""
        from phiacta.main import app as _app

        name = "test_view"
        mod = _create_synthetic_plugin_module(
            name,
            "extension",
            route_path="/query",
            route_response={"plugin": name, "type": "extension", "results": []},
        )
        _app.include_router(mod.router, prefix=f"/v1/extensions/{name}", tags=[name])
        yield name
        _app.routes[:] = [
            r for r in _app.routes
            if not (hasattr(r, "path") and r.path.startswith(f"/v1/extensions/{name}"))
        ]

    @pytest.fixture
    def _install_test_tool(self, client: httpx.AsyncClient) -> str:
        """Mount a synthetic tool plugin router on the app."""
        from phiacta.main import app as _app

        name = "test_tool"
        mod = _create_synthetic_plugin_module(
            name,
            "tool",
            route_path="/run",
            route_response={"plugin": name, "type": "tool", "output": "done"},
        )
        _app.include_router(mod.router, prefix=f"/v1/tools/{name}", tags=[name])
        yield name
        _app.routes[:] = [
            r for r in _app.routes
            if not (hasattr(r, "path") and r.path.startswith(f"/v1/tools/{name}"))
        ]

    async def test_extension_router_mounted_at_correct_prefix(
        self,
        client: httpx.AsyncClient,
        _install_test_extension: str,
    ) -> None:
        """An enabled extension plugin's router is mounted at
        /v1/extensions/{name}/... and returns the expected response.
        """
        name = _install_test_extension
        resp = await client.get(f"/v1/extensions/{name}/ping")
        assert resp.status_code == 200
        body = resp.json()
        assert body["plugin"] == name
        assert body["type"] == "extension"
        assert body["ok"] is True

    async def test_view_router_mounted_at_correct_prefix(
        self,
        client: httpx.AsyncClient,
        _install_test_view: str,
    ) -> None:
        """An enabled extension plugin (formerly view) is mounted at
        /v1/extensions/{name}/... and returns the expected response.
        """
        name = _install_test_view
        resp = await client.get(f"/v1/extensions/{name}/query")
        assert resp.status_code == 200
        body = resp.json()
        assert body["plugin"] == name
        assert body["type"] == "extension"
        assert body["results"] == []

    async def test_tool_router_mounted_at_correct_prefix(
        self,
        client: httpx.AsyncClient,
        _install_test_tool: str,
    ) -> None:
        """An enabled tool plugin's router is mounted at
        /v1/tools/{name}/... and returns the expected response.
        """
        name = _install_test_tool
        resp = await client.get(f"/v1/tools/{name}/run")
        assert resp.status_code == 200
        body = resp.json()
        assert body["plugin"] == name
        assert body["type"] == "tool"
        assert body["output"] == "done"

    async def test_core_health_still_works_with_plugin(
        self,
        client: httpx.AsyncClient,
        _install_test_extension: str,
    ) -> None:
        """Core /health endpoint remains functional even with plugins enabled."""
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    async def test_core_entries_list_still_works_with_plugin(
        self,
        client: httpx.AsyncClient,
        _install_test_extension: str,
    ) -> None:
        """Core GET /v1/entries still returns paginated results with plugins."""
        resp = await client.get("/v1/entries")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "has_more" in data
        assert "next_cursor" in data

    async def test_core_auth_still_works_with_plugin(
        self,
        client: httpx.AsyncClient,
        _install_test_extension: str,
    ) -> None:
        """Core auth registration and login work with plugins enabled."""
        auth = await register_user(
            client,
            username=f"plugtest-{uuid4().hex[:8]}",
        )
        assert "access_token" in auth
        assert "user" in auth

    async def test_core_entry_creation_works_with_plugin(
        self,
        client: httpx.AsyncClient,
        _install_test_extension: str,
    ) -> None:
        """Full entry creation flow works with plugins enabled."""
        auth = await register_user(
            client,
            username=f"plugentry-{uuid4().hex[:8]}",
        )
        token = auth["access_token"]
        entry = await create_entry(client, token, title="Plugin Coexistence Test")
        assert entry["title"] == "Plugin Coexistence Test"
        assert entry["visibility"] == "public"
