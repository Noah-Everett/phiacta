# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for update_entry_yaml() in entry_yaml.py."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import yaml

from phiacta.services.entry_yaml import generate_entry_yaml, update_entry_yaml


def _base_yaml() -> str:
    """Generate a base entry.yaml for testing."""
    return generate_entry_yaml(
        entry_id=UUID("12345678-1234-1234-1234-123456789abc"),
        title="Original Title",
        content_format="markdown",
        author_id=UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
        author_handle="test-author",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        tags=["physics", "original"],
        summary="Original summary",
        license="CC-BY-4.0",
        layout_hint="theorem",
    )


class TestUpdateEntryYaml:
    def test_update_title(self) -> None:
        result = update_entry_yaml(_base_yaml(), {"title": "New Title"})
        parsed = yaml.safe_load(result)
        assert parsed["title"] == "New Title"

    def test_update_tags(self) -> None:
        result = update_entry_yaml(_base_yaml(), {"tags": ["math", "updated"]})
        parsed = yaml.safe_load(result)
        assert parsed["tags"] == ["math", "updated"]

    def test_update_summary(self) -> None:
        result = update_entry_yaml(_base_yaml(), {"summary": "New summary"})
        parsed = yaml.safe_load(result)
        assert parsed["summary"] == "New summary"

    def test_update_content_format(self) -> None:
        result = update_entry_yaml(_base_yaml(), {"content_format": "latex"})
        parsed = yaml.safe_load(result)
        assert parsed["content_format"] == "latex"

    def test_update_license(self) -> None:
        result = update_entry_yaml(_base_yaml(), {"license": "MIT"})
        parsed = yaml.safe_load(result)
        assert parsed["license"] == "MIT"

    def test_update_layout_hint(self) -> None:
        result = update_entry_yaml(_base_yaml(), {"layout_hint": "law"})
        parsed = yaml.safe_load(result)
        assert parsed["layout_hint"] == "law"

    def test_preserves_immutable_fields(self) -> None:
        """entry_id, author, created_at, schema_version must never change."""
        result = update_entry_yaml(_base_yaml(), {"title": "Changed"})
        parsed = yaml.safe_load(result)
        assert parsed["entry_id"] == "ent_12345678-1234-1234-1234-123456789abc"
        assert parsed["author"]["id"] == "usr_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert parsed["author"]["name"] == "test-author"
        assert parsed["schema_version"] == 1

    def test_ignores_unknown_fields(self) -> None:
        """Fields not in the YAML schema should not be added."""
        result = update_entry_yaml(_base_yaml(), {"unknown_field": "value"})
        parsed = yaml.safe_load(result)
        assert "unknown_field" not in parsed

    def test_multiple_updates_at_once(self) -> None:
        result = update_entry_yaml(_base_yaml(), {
            "title": "New",
            "tags": ["new"],
            "summary": "New summary",
            "layout_hint": "law",
        })
        parsed = yaml.safe_load(result)
        assert parsed["title"] == "New"
        assert parsed["tags"] == ["new"]
        assert parsed["summary"] == "New summary"
        assert parsed["layout_hint"] == "law"
        # Unchanged
        assert parsed["license"] == "CC-BY-4.0"

    def test_clear_optional_field_with_empty_tags(self) -> None:
        """Setting tags to empty list should remove them from YAML."""
        result = update_entry_yaml(_base_yaml(), {"tags": []})
        parsed = yaml.safe_load(result)
        # Empty tags should be omitted or empty
        assert parsed.get("tags") is None or parsed.get("tags") == []

    def test_yaml_injection_safety(self) -> None:
        """User-supplied strings with YAML special chars are safe."""
        result = update_entry_yaml(_base_yaml(), {
            "title": 'Title with: colons and "quotes" and | pipes',
        })
        parsed = yaml.safe_load(result)
        assert parsed["title"] == 'Title with: colons and "quotes" and | pipes'

    def test_output_is_valid_yaml(self) -> None:
        result = update_entry_yaml(_base_yaml(), {"title": "Valid"})
        # Should not raise
        parsed = yaml.safe_load(result)
        assert isinstance(parsed, dict)
