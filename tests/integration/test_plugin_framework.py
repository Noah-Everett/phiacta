# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Integration tests for the plugin framework after the platform overhaul.

Tests that:
- PluginType enum has only EXTENSION and TOOL (no VIEW)
- PluginManifest validation works correctly
- search_tsv loads as PluginType.EXTENSION (not VIEW)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from phiacta.plugin import PluginManifest, PluginType


class TestPluginTypeEnum:
    """PluginType enum must have exactly EXTENSION and TOOL members (no VIEW)."""

    def test_has_extension_member(self) -> None:
        assert hasattr(PluginType, "EXTENSION")

    def test_has_tool_member(self) -> None:
        assert hasattr(PluginType, "TOOL")

    def test_no_view_member(self) -> None:
        assert not hasattr(PluginType, "VIEW"), (
            "PluginType.VIEW still exists -- should have been removed"
        )

    def test_exactly_two_members(self) -> None:
        members = list(PluginType)
        assert len(members) == 2
        member_names = {m.name for m in members}
        assert member_names == {"EXTENSION", "TOOL"}


class TestPluginManifestAfterOverhaul:
    def test_create_extension_manifest(self) -> None:
        manifest = PluginManifest(
            name="test_ext",
            type=PluginType.EXTENSION,
            version="1.0.0",
            description="Test extension",
        )
        assert manifest.name == "test_ext"
        assert manifest.type == PluginType.EXTENSION

    def test_create_tool_manifest(self) -> None:
        manifest = PluginManifest(
            name="test_tool",
            type=PluginType.TOOL,
            version="1.0.0",
            description="Test tool",
            depends_on=["test_ext"],
        )
        assert manifest.name == "test_tool"
        assert manifest.type == PluginType.TOOL
        assert "test_ext" in manifest.depends_on


class TestSearchTsvAsExtension:
    """search_tsv should load as PluginType.EXTENSION (moved from VIEW)."""

    def test_search_tsv_manifest_is_extension(self) -> None:
        try:
            from phiacta.extensions.search_tsv import manifest
        except ImportError:
            pytest.skip("phiacta.extensions.search_tsv not yet available")

        assert manifest.type == PluginType.EXTENSION
        assert manifest.name == "search_tsv"

    def test_old_views_search_tsv_removed(self) -> None:
        with pytest.raises(ImportError):
            import phiacta.views.search_tsv  # type: ignore[import-not-found]  # noqa: F401


class TestPluginRegistryNoViewsDirectory:
    """PluginRegistry should work without a 'view' directory key."""

    def test_discover_works_without_view_dir(self, tmp_path: Path) -> None:
        """Registry discovers plugins when plugin_dirs has no 'view' key."""
        from phiacta.plugin import PluginRegistry

        # Create a minimal extension plugin on disk
        ext_dir = tmp_path / "extensions" / "test_ext"
        ext_dir.mkdir(parents=True)
        (ext_dir / "__init__.py").write_text(
            "from phiacta.plugin import PluginManifest, PluginType\n"
            "manifest = PluginManifest(\n"
            "    name='test_ext',\n"
            "    type=PluginType.EXTENSION,\n"
            "    version='0.1.0',\n"
            "    description='Test extension',\n"
            ")\n"
        )

        registry = PluginRegistry(
            plugin_dirs={"extension": tmp_path / "extensions"},
            enabled_plugins=["test_ext"],
        )
        registry.discover()

        assert "test_ext" in registry.plugins
        assert registry.plugins["test_ext"].manifest.type == PluginType.EXTENSION

    def test_view_dir_key_is_silently_skipped(self, tmp_path: Path) -> None:
        """A 'view' key in plugin_dirs is silently skipped (no crash)."""
        from phiacta.plugin import PluginRegistry

        ext_dir = tmp_path / "extensions" / "test_ext"
        ext_dir.mkdir(parents=True)
        (ext_dir / "__init__.py").write_text(
            "from phiacta.plugin import PluginManifest, PluginType\n"
            "manifest = PluginManifest(\n"
            "    name='test_ext',\n"
            "    type=PluginType.EXTENSION,\n"
            "    version='0.1.0',\n"
            "    description='Test extension',\n"
            ")\n"
        )

        # Include a 'view' key pointing to a non-existent directory
        registry = PluginRegistry(
            plugin_dirs={
                "extension": tmp_path / "extensions",
                "view": tmp_path / "views",
            },
            enabled_plugins=["test_ext"],
        )
        registry.discover()

        assert "test_ext" in registry.plugins

    def test_default_plugin_dirs_has_no_view_key(self) -> None:
        """The default PluginRegistry plugin_dirs should not include a 'view' key."""
        from phiacta.plugin import PluginRegistry

        registry = PluginRegistry(enabled_plugins=[])
        # Access the internal plugin_dirs to verify no 'view' key
        assert "view" not in registry._plugin_dirs


class TestSearchTsvManifestDependsOn:
    """search_tsv manifest should have correct depends_on."""

    def test_search_tsv_has_empty_depends_on(self) -> None:
        from phiacta.extensions.search_tsv import manifest

        assert manifest.depends_on == [], (
            f"search_tsv depends_on should be empty, got {manifest.depends_on}"
        )


class TestSearchToolManifestDependsOn:
    """search tool manifest should declare dependency on search_tsv."""

    def test_search_tool_depends_on_search_tsv(self) -> None:
        from phiacta.tools.search import manifest

        assert "search_tsv" in manifest.depends_on, (
            f"search tool should depend on search_tsv, "
            f"got depends_on={manifest.depends_on}"
        )
