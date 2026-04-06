# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Integration tests for the PluginRegistry (NEV-199).

Tests plugin discovery, dependency resolution, router prefix generation,
settings instantiation, and error handling. Uses tmp_path to build minimal
plugin packages on disk for realistic discovery testing.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from fastapi import APIRouter
from phiacta.plugin import PluginManifest, PluginRegistry, PluginType

# ---------------------------------------------------------------------------
# Helpers: create minimal plugin packages on disk
# ---------------------------------------------------------------------------


def _write_plugin_package(
    base_dir: Path,
    plugin_type_dir: str,
    name: str,
    *,
    manifest_type: str = "extension",
    version: str = "0.1.0",
    depends_on: list[str] | None = None,
    has_router: bool = True,
    settings_class_code: str | None = None,
    broken_import: bool = False,
) -> Path:
    """Create a minimal plugin package directory under base_dir.

    Layout:
        base_dir/<plugin_type_dir>/<name>/__init__.py

    The __init__.py exports a ``manifest`` attribute and optionally a ``router``.
    """
    plugin_dir = base_dir / plugin_type_dir / name
    plugin_dir.mkdir(parents=True, exist_ok=True)

    deps_str = repr(depends_on or [])

    settings_import = ""
    settings_ref = "None"
    if settings_class_code:
        settings_import = settings_class_code
        settings_ref = f"{name.title()}Settings"

    router_code = ""
    if has_router:
        router_code = (
            "from fastapi import APIRouter\n"
            "router = APIRouter()\n"
            "\n"
            "@router.get('/ping')\n"
            "async def ping():\n"
            f"    return {{\"plugin\": \"{name}\", \"status\": \"ok\"}}\n"
        )

    if broken_import:
        init_content = "raise ImportError('Simulated broken plugin')\n"
    else:
        init_content = (
            "from phiacta.plugin import PluginManifest, PluginType\n"
            "\n"
            f"{settings_import}\n"
            "\n"
            "manifest = PluginManifest(\n"
            f"    name=\"{name}\",\n"
            f"    type=PluginType.{manifest_type.upper()},\n"
            f"    version=\"{version}\",\n"
            f"    depends_on={deps_str},\n"
            f"    description=\"Test plugin: {name}\",\n"
            f"    settings_class={settings_ref},\n"
            ")\n"
            "\n"
            f"{router_code}"
        )

    (plugin_dir / "__init__.py").write_text(init_content)
    return plugin_dir


def _make_in_memory_manifest(
    name: str,
    plugin_type: str = "extension",
    depends_on: list[str] | None = None,
    settings_class: type | None = None,
) -> PluginManifest:
    """Create a PluginManifest without touching the filesystem."""
    type_map = {
        "extension": PluginType.EXTENSION,
        "tool": PluginType.TOOL,
    }
    return PluginManifest(
        name=name,
        type=type_map[plugin_type],
        version="0.1.0",
        depends_on=depends_on or [],
        description=f"In-memory plugin: {name}",
        settings_class=settings_class,
    )


# ---------------------------------------------------------------------------
# Discovery tests
# ---------------------------------------------------------------------------


class TestPluginDiscovery:
    """Tests that PluginRegistry correctly discovers plugin packages from
    the filesystem and respects the enabled_plugins configuration.
    """

    def test_discovers_valid_plugin_from_directory(
        self, tmp_path: Path
    ) -> None:
        """Registry discovers a plugin with a valid __init__.py containing
        a manifest attribute.
        """
        _write_plugin_package(
            tmp_path, "extensions", "tags", manifest_type="extension"
        )

        registry = PluginRegistry(
            plugin_dirs={"extension": tmp_path / "extensions"},
            enabled_plugins=["tags"],
        )
        registry.discover()

        assert "tags" in registry.plugins
        assert registry.plugins["tags"].manifest.name == "tags"
        assert registry.plugins["tags"].manifest.type == PluginType.EXTENSION

    def test_skips_plugin_not_in_enabled_list(
        self, tmp_path: Path
    ) -> None:
        """Plugins that exist on disk but are NOT in enabled_plugins are
        not loaded.
        """
        _write_plugin_package(
            tmp_path, "extensions", "tags", manifest_type="extension"
        )
        _write_plugin_package(
            tmp_path, "extensions", "categories", manifest_type="extension"
        )

        registry = PluginRegistry(
            plugin_dirs={"extension": tmp_path / "extensions"},
            enabled_plugins=["tags"],
        )
        registry.discover()

        assert "tags" in registry.plugins
        assert "categories" not in registry.plugins

    def test_empty_enabled_plugins_loads_nothing(
        self, tmp_path: Path
    ) -> None:
        """When enabled_plugins is empty, no plugins are loaded even if they
        exist on disk.
        """
        _write_plugin_package(
            tmp_path, "extensions", "tags", manifest_type="extension"
        )

        registry = PluginRegistry(
            plugin_dirs={"extension": tmp_path / "extensions"},
            enabled_plugins=[],
        )
        registry.discover()

        assert len(registry.plugins) == 0

    def test_raises_on_enabled_plugin_not_on_disk(
        self, tmp_path: Path
    ) -> None:
        """When an enabled plugin is listed in config but does not exist on
        disk, discovery raises ValueError.
        """
        registry = PluginRegistry(
            plugin_dirs={"extension": tmp_path / "extensions"},
            enabled_plugins=["nonexistent_plugin"],
        )

        with pytest.raises(ValueError, match="nonexistent_plugin"):
            registry.discover()

    def test_raises_on_broken_plugin_import(
        self, tmp_path: Path
    ) -> None:
        """When an enabled plugin has a broken __init__.py (import error),
        discovery crashes with a clear error message.
        """
        _write_plugin_package(
            tmp_path,
            "extensions",
            "broken",
            manifest_type="extension",
            broken_import=True,
        )

        registry = PluginRegistry(
            plugin_dirs={"extension": tmp_path / "extensions"},
            enabled_plugins=["broken"],
        )

        with pytest.raises((ImportError, ValueError)):
            registry.discover()

    def test_raises_on_duplicate_plugin_name(
        self, tmp_path: Path
    ) -> None:
        """Two plugins with the same name (across types) raise ValueError."""
        _write_plugin_package(
            tmp_path, "extensions", "duplicate", manifest_type="extension"
        )
        _write_plugin_package(
            tmp_path, "tools", "duplicate", manifest_type="tool"
        )

        registry = PluginRegistry(
            plugin_dirs={
                "extension": tmp_path / "extensions",
                "tool": tmp_path / "tools",
            },
            enabled_plugins=["duplicate"],
        )

        with pytest.raises(ValueError, match=r"[Dd]uplicate"):
            registry.discover()

    def test_discovers_multiple_plugin_types(
        self, tmp_path: Path
    ) -> None:
        """Registry discovers plugins across extension and tool dirs."""
        _write_plugin_package(
            tmp_path, "extensions", "tags", manifest_type="extension"
        )
        _write_plugin_package(
            tmp_path, "tools", "export", manifest_type="tool"
        )

        registry = PluginRegistry(
            plugin_dirs={
                "extension": tmp_path / "extensions",
                "tool": tmp_path / "tools",
            },
            enabled_plugins=["tags", "export"],
        )
        registry.discover()

        assert len(registry.plugins) == 2
        assert registry.plugins["tags"].manifest.type == PluginType.EXTENSION
        assert registry.plugins["export"].manifest.type == PluginType.TOOL


# ---------------------------------------------------------------------------
# Dependency resolution tests
# ---------------------------------------------------------------------------


class TestDependencyResolver:
    """Tests the topological sort dependency resolver used by the registry
    to determine plugin load order.
    """

    def test_valid_dependency_chain(self, tmp_path: Path) -> None:
        """A -> B dependency graph resolves correctly: B loads before A."""
        _write_plugin_package(
            tmp_path,
            "extensions",
            "base_ext",
            manifest_type="extension",
            depends_on=[],
        )
        _write_plugin_package(
            tmp_path,
            "extensions",
            "derived_ext",
            manifest_type="extension",
            depends_on=["base_ext"],
        )

        registry = PluginRegistry(
            plugin_dirs={"extension": tmp_path / "extensions"},
            enabled_plugins=["base_ext", "derived_ext"],
        )
        registry.discover()
        order = registry.resolve_dependencies()

        # base_ext must come before derived_ext in the load order
        base_idx = order.index("base_ext")
        derived_idx = order.index("derived_ext")
        assert base_idx < derived_idx

    def test_no_dependencies_resolves(self, tmp_path: Path) -> None:
        """Plugins with no dependencies resolve in any order without error."""
        _write_plugin_package(
            tmp_path, "extensions", "alpha", manifest_type="extension"
        )
        _write_plugin_package(
            tmp_path, "extensions", "beta", manifest_type="extension"
        )

        registry = PluginRegistry(
            plugin_dirs={"extension": tmp_path / "extensions"},
            enabled_plugins=["alpha", "beta"],
        )
        registry.discover()
        order = registry.resolve_dependencies()

        assert set(order) == {"alpha", "beta"}

    def test_rejects_missing_dependency(self, tmp_path: Path) -> None:
        """A plugin depending on a non-existent plugin raises ValueError
        naming the missing dependency.
        """
        _write_plugin_package(
            tmp_path,
            "extensions",
            "needs_missing",
            manifest_type="extension",
            depends_on=["does_not_exist"],
        )

        registry = PluginRegistry(
            plugin_dirs={"extension": tmp_path / "extensions"},
            enabled_plugins=["needs_missing"],
        )
        registry.discover()

        with pytest.raises(ValueError, match="does_not_exist"):
            registry.resolve_dependencies()

    def test_rejects_circular_dependency(self, tmp_path: Path) -> None:
        """A -> B -> A circular dependency raises ValueError listing the cycle."""
        _write_plugin_package(
            tmp_path,
            "extensions",
            "cycle_a",
            manifest_type="extension",
            depends_on=["cycle_b"],
        )
        _write_plugin_package(
            tmp_path,
            "extensions",
            "cycle_b",
            manifest_type="extension",
            depends_on=["cycle_a"],
        )

        registry = PluginRegistry(
            plugin_dirs={"extension": tmp_path / "extensions"},
            enabled_plugins=["cycle_a", "cycle_b"],
        )
        registry.discover()

        with pytest.raises(ValueError, match=r"[Cc]ircl|[Cc]ycl"):
            registry.resolve_dependencies()

    def test_rejects_self_dependency(self, tmp_path: Path) -> None:
        """A plugin depending on itself raises ValueError."""
        _write_plugin_package(
            tmp_path,
            "extensions",
            "self_dep",
            manifest_type="extension",
            depends_on=["self_dep"],
        )

        registry = PluginRegistry(
            plugin_dirs={"extension": tmp_path / "extensions"},
            enabled_plugins=["self_dep"],
        )
        registry.discover()

        with pytest.raises(ValueError, match="self_dep"):
            registry.resolve_dependencies()

    def test_diamond_dependency_resolves(self, tmp_path: Path) -> None:
        """Diamond: D depends on B and C; B and C both depend on A.
        Should resolve without error.
        """
        _write_plugin_package(
            tmp_path,
            "extensions",
            "diamond_a",
            manifest_type="extension",
            depends_on=[],
        )
        _write_plugin_package(
            tmp_path,
            "extensions",
            "diamond_b",
            manifest_type="extension",
            depends_on=["diamond_a"],
        )
        _write_plugin_package(
            tmp_path,
            "extensions",
            "diamond_c",
            manifest_type="extension",
            depends_on=["diamond_a"],
        )
        _write_plugin_package(
            tmp_path,
            "extensions",
            "diamond_d",
            manifest_type="extension",
            depends_on=["diamond_b", "diamond_c"],
        )

        registry = PluginRegistry(
            plugin_dirs={"extension": tmp_path / "extensions"},
            enabled_plugins=["diamond_a", "diamond_b", "diamond_c", "diamond_d"],
        )
        registry.discover()
        order = registry.resolve_dependencies()

        # A must come before B, C, D
        a_idx = order.index("diamond_a")
        b_idx = order.index("diamond_b")
        c_idx = order.index("diamond_c")
        d_idx = order.index("diamond_d")
        assert a_idx < b_idx
        assert a_idx < c_idx
        assert b_idx < d_idx
        assert c_idx < d_idx


# ---------------------------------------------------------------------------
# Plugin settings tests
# ---------------------------------------------------------------------------


class TestPluginSettings:
    """Tests that the registry correctly instantiates and provides
    plugin-specific settings classes.
    """

    def test_settings_instantiated_on_discovery(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A plugin with a settings_class has its settings instantiated
        during discovery.
        """
        settings_code = textwrap.dedent("""\
            from pydantic_settings import BaseSettings

            class TagsSettings(BaseSettings):
                tags_max_count: int = 50
                model_config = {"env_prefix": "TAGS_"}
        """)

        _write_plugin_package(
            tmp_path,
            "extensions",
            "tags",
            manifest_type="extension",
            settings_class_code=settings_code,
        )

        registry = PluginRegistry(
            plugin_dirs={"extension": tmp_path / "extensions"},
            enabled_plugins=["tags"],
        )
        registry.discover()

        settings = registry.get_settings("tags")
        assert settings is not None
        assert settings.tags_max_count == 50  # type: ignore[attr-defined]

    def test_settings_missing_required_env_var_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A plugin with a settings_class that requires env vars raises
        ValueError with a clear message naming the plugin when those vars
        are missing.
        """
        settings_code = textwrap.dedent("""\
            from pydantic_settings import BaseSettings

            class SearchSettings(BaseSettings):
                search_api_key: str  # required, no default
                model_config = {"env_prefix": "SEARCH_"}
        """)

        _write_plugin_package(
            tmp_path,
            "extensions",
            "search",
            manifest_type="extension",
            settings_class_code=settings_code,
        )

        # Ensure the required env var is NOT set
        monkeypatch.delenv("SEARCH_SEARCH_API_KEY", raising=False)
        monkeypatch.delenv("SEARCH_API_KEY", raising=False)

        registry = PluginRegistry(
            plugin_dirs={"extension": tmp_path / "extensions"},
            enabled_plugins=["search"],
        )

        with pytest.raises(ValueError, match="search"):
            registry.discover()

    def test_get_settings_returns_correct_instance(
        self, tmp_path: Path
    ) -> None:
        """get_settings(name) returns the exact settings instance for that plugin."""
        settings_code = textwrap.dedent("""\
            from pydantic_settings import BaseSettings

            class ExportSettings(BaseSettings):
                export_format: str = "json"
                model_config = {"env_prefix": "EXPORT_"}
        """)

        _write_plugin_package(
            tmp_path,
            "tools",
            "export",
            manifest_type="tool",
            settings_class_code=settings_code,
        )

        registry = PluginRegistry(
            plugin_dirs={"tool": tmp_path / "tools"},
            enabled_plugins=["export"],
        )
        registry.discover()

        settings = registry.get_settings("export")
        assert settings is not None
        assert settings.export_format == "json"  # type: ignore[attr-defined]

    def test_get_settings_returns_none_for_plugin_without_settings(
        self, tmp_path: Path
    ) -> None:
        """get_settings(name) returns None for a plugin with no settings_class."""
        _write_plugin_package(
            tmp_path, "extensions", "simple", manifest_type="extension"
        )

        registry = PluginRegistry(
            plugin_dirs={"extension": tmp_path / "extensions"},
            enabled_plugins=["simple"],
        )
        registry.discover()

        assert registry.get_settings("simple") is None

    def test_get_settings_unknown_plugin_raises_or_returns_none(
        self, tmp_path: Path
    ) -> None:
        """get_settings for an unknown plugin name raises KeyError or returns None."""
        registry = PluginRegistry(
            plugin_dirs={"extension": tmp_path / "extensions"},
            enabled_plugins=[],
        )
        registry.discover()

        with pytest.raises((KeyError, ValueError)):
            registry.get_settings("totally_unknown")


# ---------------------------------------------------------------------------
# Router prefix generation tests
# ---------------------------------------------------------------------------


class TestRouterPrefixes:
    """Tests that get_routers() returns the correct URL prefix for each
    plugin type.
    """

    def test_extension_router_prefix(self, tmp_path: Path) -> None:
        """Extension plugins get prefix /v1/extensions/{name}/."""
        _write_plugin_package(
            tmp_path, "extensions", "tags", manifest_type="extension"
        )

        registry = PluginRegistry(
            plugin_dirs={"extension": tmp_path / "extensions"},
            enabled_plugins=["tags"],
        )
        registry.discover()
        routers = registry.get_routers()

        assert len(routers) >= 1
        prefixes = {prefix for prefix, _ in routers}
        assert "/v1/extensions/tags" in prefixes

    def test_second_extension_router_prefix(self, tmp_path: Path) -> None:
        """A second extension plugin also gets prefix /v1/extensions/{name}/."""
        _write_plugin_package(
            tmp_path, "extensions", "search", manifest_type="extension"
        )

        registry = PluginRegistry(
            plugin_dirs={"extension": tmp_path / "extensions"},
            enabled_plugins=["search"],
        )
        registry.discover()
        routers = registry.get_routers()

        prefixes = {prefix for prefix, _ in routers}
        assert "/v1/extensions/search" in prefixes

    def test_tool_router_prefix(self, tmp_path: Path) -> None:
        """Tool plugins get prefix /v1/tools/{name}/."""
        _write_plugin_package(
            tmp_path, "tools", "export", manifest_type="tool"
        )

        registry = PluginRegistry(
            plugin_dirs={"tool": tmp_path / "tools"},
            enabled_plugins=["export"],
        )
        registry.discover()
        routers = registry.get_routers()

        prefixes = {prefix for prefix, _ in routers}
        assert "/v1/tools/export" in prefixes

    def test_plugin_without_router_excluded_from_get_routers(
        self, tmp_path: Path
    ) -> None:
        """A plugin that has no router attribute is not included in get_routers."""
        _write_plugin_package(
            tmp_path,
            "extensions",
            "headless",
            manifest_type="extension",
            has_router=False,
        )

        registry = PluginRegistry(
            plugin_dirs={"extension": tmp_path / "extensions"},
            enabled_plugins=["headless"],
        )
        registry.discover()
        routers = registry.get_routers()

        prefixes = {prefix for prefix, _ in routers}
        assert "/v1/extensions/headless" not in prefixes

    def test_routers_are_fastapi_apirouter_instances(
        self, tmp_path: Path
    ) -> None:
        """Each router returned by get_routers() is a FastAPI APIRouter."""
        _write_plugin_package(
            tmp_path, "extensions", "tags", manifest_type="extension"
        )

        registry = PluginRegistry(
            plugin_dirs={"extension": tmp_path / "extensions"},
            enabled_plugins=["tags"],
        )
        registry.discover()
        routers = registry.get_routers()

        for prefix, router in routers:
            assert isinstance(prefix, str)
            assert isinstance(router, APIRouter)

    def test_multiple_plugins_correct_prefixes(
        self, tmp_path: Path
    ) -> None:
        """Multiple plugins of different types get correct prefixes."""
        _write_plugin_package(
            tmp_path, "extensions", "tags", manifest_type="extension"
        )
        _write_plugin_package(
            tmp_path, "tools", "export", manifest_type="tool"
        )

        registry = PluginRegistry(
            plugin_dirs={
                "extension": tmp_path / "extensions",
                "tool": tmp_path / "tools",
            },
            enabled_plugins=["tags", "export"],
        )
        registry.discover()
        routers = registry.get_routers()

        prefixes = {prefix for prefix, _ in routers}
        assert "/v1/extensions/tags" in prefixes
        assert "/v1/tools/export" in prefixes
