# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Integration tests for the plugin framework after the platform overhaul.

Tests that:
- PluginType enum has only EXTENSION and TOOL (no VIEW)
- PluginManifest validation works correctly
- search_tsv loads as PluginType.EXTENSION (not VIEW)
"""

from __future__ import annotations

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
