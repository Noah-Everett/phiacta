# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for PluginManifest and PluginType (NEV-199).

Tests the frozen dataclass and enum that define plugin metadata.
These are pure data classes with no I/O or database interaction.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from phiacta.plugin import PluginManifest, PluginType

# ---------------------------------------------------------------------------
# PluginType enum tests
# ---------------------------------------------------------------------------


class TestPluginType:
    """PluginType enum must have exactly EXTENSION, VIEW, TOOL members."""

    def test_has_extension_member(self) -> None:
        """PluginType.EXTENSION exists."""
        assert hasattr(PluginType, "EXTENSION")
        assert PluginType.EXTENSION is not None

    def test_has_tool_member(self) -> None:
        """PluginType.TOOL exists."""
        assert hasattr(PluginType, "TOOL")
        assert PluginType.TOOL is not None

    def test_no_view_member(self) -> None:
        """PluginType.VIEW was removed in the platform overhaul."""
        assert not hasattr(PluginType, "VIEW")

    def test_exactly_two_members(self) -> None:
        """PluginType has exactly two members: EXTENSION, TOOL."""
        members = list(PluginType)
        assert len(members) == 2
        member_names = {m.name for m in members}
        assert member_names == {"EXTENSION", "TOOL"}

    def test_members_are_distinct(self) -> None:
        """Each PluginType member has a distinct value."""
        values = [m.value for m in PluginType]
        assert len(values) == len(set(values))

    def test_extension_is_not_tool(self) -> None:
        """EXTENSION and TOOL are different enum members."""
        assert PluginType.EXTENSION != PluginType.TOOL

    def test_extension_is_not_tool(self) -> None:
        """EXTENSION and TOOL are different enum members."""
        assert PluginType.EXTENSION != PluginType.TOOL


# ---------------------------------------------------------------------------
# PluginManifest construction tests
# ---------------------------------------------------------------------------


class TestPluginManifestConstruction:
    """Tests for constructing PluginManifest with all fields and with defaults."""

    def test_all_fields_provided(self) -> None:
        """PluginManifest stores all provided fields correctly."""
        from pydantic_settings import BaseSettings

        class FakeSettings(BaseSettings):
            fake_key: str = "value"

        manifest = PluginManifest(
            name="tags",
            type=PluginType.EXTENSION,
            version="1.2.3",
            depends_on=["core_ext"],
            description="Tagging extension for entries",
            settings_class=FakeSettings,
        )

        assert manifest.name == "tags"
        assert manifest.type == PluginType.EXTENSION
        assert manifest.version == "1.2.3"
        assert manifest.depends_on == ["core_ext"]
        assert manifest.description == "Tagging extension for entries"
        assert manifest.settings_class is FakeSettings

    def test_minimal_fields_with_defaults(self) -> None:
        """PluginManifest with only required fields uses correct defaults."""
        manifest = PluginManifest(
            name="simple",
            type=PluginType.EXTENSION,
            version="0.1.0",
        )

        assert manifest.name == "simple"
        assert manifest.type == PluginType.EXTENSION
        assert manifest.version == "0.1.0"
        # depends_on defaults to empty list
        assert manifest.depends_on == []
        # description defaults to empty string
        assert manifest.description == ""
        # settings_class defaults to None
        assert manifest.settings_class is None

    def test_depends_on_default_is_empty(self) -> None:
        """depends_on defaults to an empty list (not None)."""
        manifest = PluginManifest(
            name="no_deps",
            type=PluginType.TOOL,
            version="1.0.0",
        )
        # Should be falsy (empty list or None)
        assert not manifest.depends_on

    def test_settings_class_default_is_none(self) -> None:
        """settings_class defaults to None when not provided."""
        manifest = PluginManifest(
            name="no_settings",
            type=PluginType.EXTENSION,
            version="1.0.0",
        )
        assert manifest.settings_class is None

    def test_multiple_dependencies(self) -> None:
        """depends_on accepts multiple dependency names."""
        manifest = PluginManifest(
            name="complex",
            type=PluginType.TOOL,
            version="2.0.0",
            depends_on=["tags", "categories", "interactions"],
        )
        assert len(manifest.depends_on) == 3
        assert "tags" in manifest.depends_on
        assert "categories" in manifest.depends_on
        assert "interactions" in manifest.depends_on


# ---------------------------------------------------------------------------
# PluginManifest immutability tests
# ---------------------------------------------------------------------------


class TestPluginManifestImmutability:
    """PluginManifest is a frozen dataclass -- fields cannot be mutated."""

    def test_cannot_change_name(self) -> None:
        """Assigning to manifest.name raises an error."""
        manifest = PluginManifest(
            name="immutable",
            type=PluginType.EXTENSION,
            version="1.0.0",
        )
        with pytest.raises((AttributeError, TypeError, FrozenInstanceError)):
            manifest.name = "changed"  # type: ignore[misc]

    def test_cannot_change_type(self) -> None:
        """Assigning to manifest.type raises an error."""
        manifest = PluginManifest(
            name="immutable",
            type=PluginType.EXTENSION,
            version="1.0.0",
        )
        with pytest.raises((AttributeError, TypeError, FrozenInstanceError)):
            manifest.type = PluginType.TOOL  # type: ignore[misc]

    def test_cannot_change_version(self) -> None:
        """Assigning to manifest.version raises an error."""
        manifest = PluginManifest(
            name="immutable",
            type=PluginType.EXTENSION,
            version="1.0.0",
        )
        with pytest.raises((AttributeError, TypeError, FrozenInstanceError)):
            manifest.version = "2.0.0"  # type: ignore[misc]

    def test_cannot_change_depends_on(self) -> None:
        """Assigning to manifest.depends_on raises an error."""
        manifest = PluginManifest(
            name="immutable",
            type=PluginType.EXTENSION,
            version="1.0.0",
            depends_on=[],
        )
        with pytest.raises((AttributeError, TypeError, FrozenInstanceError)):
            manifest.depends_on = ["something"]  # type: ignore[misc]

    def test_cannot_change_description(self) -> None:
        """Assigning to manifest.description raises an error."""
        manifest = PluginManifest(
            name="immutable",
            type=PluginType.EXTENSION,
            version="1.0.0",
            description="original",
        )
        with pytest.raises((AttributeError, TypeError, FrozenInstanceError)):
            manifest.description = "changed"  # type: ignore[misc]

    def test_cannot_add_new_attribute(self) -> None:
        """Adding a new attribute to a frozen manifest raises an error."""
        manifest = PluginManifest(
            name="immutable",
            type=PluginType.EXTENSION,
            version="1.0.0",
        )
        with pytest.raises((AttributeError, TypeError, FrozenInstanceError)):
            manifest.new_field = "nope"  # type: ignore[attr-defined]
