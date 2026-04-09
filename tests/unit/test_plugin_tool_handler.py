# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Tests for job_handler registration in the plugin system."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest

from phiacta.plugin import PluginManifest, PluginRegistry, PluginRegistration, PluginType
from phiacta.tools.base import JobContext, JobHandler


class _DummyHandler(JobHandler):
    async def run(self, input: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        return {}


class TestPluginRegistrationJobHandler:
    def test_job_handler_defaults_to_none(self) -> None:
        reg = PluginRegistration(
            manifest=PluginManifest(name="test", type=PluginType.TOOL, version="1.0.0"),
        )
        assert reg.job_handler is None

    def test_job_handler_can_be_set(self) -> None:
        handler = _DummyHandler()
        reg = PluginRegistration(
            manifest=PluginManifest(name="test", type=PluginType.TOOL, version="1.0.0"),
            job_handler=handler,
        )
        assert reg.job_handler is handler


class TestPluginRegistryGetJobHandlers:
    def test_returns_empty_when_no_handlers(self) -> None:
        registry = PluginRegistry(enabled_plugins=[])
        assert registry.get_job_handlers() == {}

    def test_returns_registered_handlers(self) -> None:
        handler = _DummyHandler()
        registry = PluginRegistry(enabled_plugins=[])
        # Manually register a plugin with a handler
        registry._plugins["latex"] = PluginRegistration(
            manifest=PluginManifest(name="latex", type=PluginType.TOOL, version="1.0.0"),
            job_handler=handler,
        )
        result = registry.get_job_handlers()
        assert "latex" in result
        assert result["latex"] is handler

    def test_excludes_plugins_without_handler(self) -> None:
        registry = PluginRegistry(enabled_plugins=[])
        registry._plugins["search"] = PluginRegistration(
            manifest=PluginManifest(name="search", type=PluginType.TOOL, version="1.0.0"),
        )
        registry._plugins["latex"] = PluginRegistration(
            manifest=PluginManifest(name="latex", type=PluginType.TOOL, version="1.0.0"),
            job_handler=_DummyHandler(),
        )
        result = registry.get_job_handlers()
        assert "search" not in result
        assert "latex" in result


class TestPluginDiscoveryJobHandler:
    """Test that discover() picks up job_handler from plugin modules."""

    def test_discovers_job_handler(self, tmp_path: Path) -> None:
        """Create a fake tool plugin with a job_handler and verify discovery."""
        tool_dir = tmp_path / "tools" / "fake_tool"
        tool_dir.mkdir(parents=True)

        (tool_dir / "__init__.py").write_text(dedent("""\
            from phiacta.plugin import PluginManifest, PluginType
            from phiacta.tools.base import JobHandler, JobContext
            from typing import Any

            manifest = PluginManifest(
                name="fake_tool",
                type=PluginType.TOOL,
                version="1.0.0",
            )

            class FakeHandler(JobHandler):
                async def run(self, input: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
                    return {"fake": True}

            job_handler = FakeHandler()
        """))

        registry = PluginRegistry(
            plugin_dirs={"tool": tmp_path / "tools"},
            enabled_plugins=["fake_tool"],
        )
        registry.discover()

        handlers = registry.get_job_handlers()
        assert "fake_tool" in handlers

    def test_plugin_without_handler_still_works(self, tmp_path: Path) -> None:
        """Existing tools without job_handler should still load fine."""
        tool_dir = tmp_path / "tools" / "simple_tool"
        tool_dir.mkdir(parents=True)

        (tool_dir / "__init__.py").write_text(dedent("""\
            from phiacta.plugin import PluginManifest, PluginType

            manifest = PluginManifest(
                name="simple_tool",
                type=PluginType.TOOL,
                version="1.0.0",
            )
        """))

        registry = PluginRegistry(
            plugin_dirs={"tool": tmp_path / "tools"},
            enabled_plugins=["simple_tool"],
        )
        registry.discover()

        handlers = registry.get_job_handlers()
        assert "simple_tool" not in handlers
        # But the plugin itself is registered
        assert "simple_tool" in registry.plugins
