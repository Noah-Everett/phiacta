# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for entry YAML generation and parsing (NEV-117/NEV-118).

Tests the functions that generate .phiacta/entry.yaml content and parse
it back. These functions are used by the outbox worker (to create the
initial commit) and the webhook handler (to parse updates).
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import yaml

from phiacta.services.entry_yaml import generate_entry_yaml, parse_entry_yaml


class TestGenerateEntryYaml:
    """Tests for YAML generation from entry metadata."""

    def test_entry_yaml_generation_minimal(self) -> None:
        """Generate entry.yaml with only required fields produces valid YAML."""
        entry_id = uuid4()
        created_at = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = generate_entry_yaml(
            entry_id=entry_id,
            title="Minimal Entry",
            content_format="markdown",
            author_id=uuid4(),
            author_handle="alice",
            created_at=created_at,
        )
        # Must be valid YAML
        parsed = yaml.safe_load(result)
        assert parsed is not None
        assert parsed["title"] == "Minimal Entry"
        assert parsed["content_format"] == "markdown"
        assert "schema_version" in parsed
        assert parsed["author"]["name"] == "alice"

    def test_entry_yaml_generation_full(self) -> None:
        """Generate entry.yaml with all fields populates every expected key."""
        entry_id = uuid4()
        author_id = uuid4()
        created_at = datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        result = generate_entry_yaml(
            entry_id=entry_id,
            title="Full Entry with All Fields",
            content_format="latex",
            author_id=author_id,
            author_handle="bob-researcher",
            created_at=created_at,
            tags=["quantum-mechanics", "entanglement"],
            summary="A comprehensive study of quantum entanglement.",
            license="CC-BY-SA-4.0",
            layout_hint="research-paper",
        )
        parsed = yaml.safe_load(result)
        assert parsed["title"] == "Full Entry with All Fields"
        assert parsed["content_format"] == "latex"
        assert parsed["tags"] == ["quantum-mechanics", "entanglement"]
        assert parsed["summary"] == "A comprehensive study of quantum entanglement."
        assert parsed["license"] == "CC-BY-SA-4.0"
        assert parsed["layout_hint"] == "research-paper"
        assert parsed["author"]["name"] == "bob-researcher"
        assert str(author_id) in str(parsed["author"]["id"])

    def test_entry_yaml_entry_id_has_prefix(self) -> None:
        """entry_id in YAML must start with 'ent_' prefix."""
        entry_id = uuid4()
        result = generate_entry_yaml(
            entry_id=entry_id,
            title="Prefix Test",
            content_format="markdown",
            author_id=uuid4(),
            author_handle="carol",
            created_at=datetime.now(tz=timezone.utc),
        )
        parsed = yaml.safe_load(result)
        yaml_entry_id = parsed["entry_id"]
        assert yaml_entry_id.startswith("ent_")
        # The UUID portion after the prefix should match
        assert str(entry_id) in yaml_entry_id

    def test_entry_yaml_schema_version_present(self) -> None:
        """Generated YAML must include schema_version."""
        result = generate_entry_yaml(
            entry_id=uuid4(),
            title="Schema Version Test",
            content_format="plain",
            author_id=uuid4(),
            author_handle="dave",
            created_at=datetime.now(tz=timezone.utc),
        )
        parsed = yaml.safe_load(result)
        assert "schema_version" in parsed
        assert isinstance(parsed["schema_version"], int)

    def test_entry_yaml_special_characters_in_title(self) -> None:
        """Title with colons, quotes, unicode produces valid YAML that round-trips."""
        tricky_titles = [
            'Title: with "colons" and quotes',
            "Euler's formula: e^{i\\pi} + 1 = 0",
            "Schrodinger equation",
            "Japanese: \u91cf\u5b50\u529b\u5b66",
            "Emoji-free but with symbols: @#$%^&*()",
            "Newline\\nin title",
            "Tab\\tin title",
        ]
        for title in tricky_titles:
            result = generate_entry_yaml(
                entry_id=uuid4(),
                title=title,
                content_format="markdown",
                author_id=uuid4(),
                author_handle="special-chars",
                created_at=datetime.now(tz=timezone.utc),
            )
            parsed = yaml.safe_load(result)
            assert parsed["title"] == title, f"Round-trip failed for: {title!r}"

    def test_entry_yaml_null_optional_fields(self) -> None:
        """None values for optional fields are either omitted or null in YAML."""
        result = generate_entry_yaml(
            entry_id=uuid4(),
            title="Null Fields Test",
            content_format="markdown",
            author_id=uuid4(),
            author_handle="eve",
            created_at=datetime.now(tz=timezone.utc),
            tags=None,
            summary=None,
            license=None,
            layout_hint=None,
        )
        parsed = yaml.safe_load(result)
        # Required fields must be present
        assert parsed["title"] == "Null Fields Test"
        assert parsed["content_format"] == "markdown"
        # Optional fields either absent or explicitly null
        for field in ("tags", "summary", "license", "layout_hint"):
            if field in parsed:
                assert parsed[field] is None or parsed[field] == [], (
                    f"{field} should be None or [] when not provided, got {parsed[field]!r}"
                )

    def test_entry_yaml_tags_as_list(self) -> None:
        """Tags must be serialized as a YAML list, not a string."""
        result = generate_entry_yaml(
            entry_id=uuid4(),
            title="Tags Test",
            content_format="markdown",
            author_id=uuid4(),
            author_handle="frank",
            created_at=datetime.now(tz=timezone.utc),
            tags=["alpha", "beta", "gamma"],
        )
        parsed = yaml.safe_load(result)
        assert isinstance(parsed["tags"], list)
        assert parsed["tags"] == ["alpha", "beta", "gamma"]

    def test_entry_yaml_empty_tags_list(self) -> None:
        """Empty tags list serializes correctly."""
        result = generate_entry_yaml(
            entry_id=uuid4(),
            title="Empty Tags Test",
            content_format="markdown",
            author_id=uuid4(),
            author_handle="grace",
            created_at=datetime.now(tz=timezone.utc),
            tags=[],
        )
        parsed = yaml.safe_load(result)
        # Either absent, null, or empty list -- all are acceptable
        tags = parsed.get("tags")
        assert tags is None or tags == []

    def test_entry_yaml_created_at_present(self) -> None:
        """created_at must be in the generated YAML."""
        ts = datetime(2026, 6, 15, 8, 45, 0, tzinfo=timezone.utc)
        result = generate_entry_yaml(
            entry_id=uuid4(),
            title="Timestamp Test",
            content_format="markdown",
            author_id=uuid4(),
            author_handle="heidi",
            created_at=ts,
        )
        parsed = yaml.safe_load(result)
        assert "created_at" in parsed


class TestParseEntryYaml:
    """Tests for parsing .phiacta/entry.yaml content back into structured data."""

    def test_entry_yaml_roundtrip(self) -> None:
        """Generate then parse produces the same values."""
        entry_id = uuid4()
        author_id = uuid4()
        created_at = datetime(2026, 3, 15, 14, 0, 0, tzinfo=timezone.utc)
        yaml_str = generate_entry_yaml(
            entry_id=entry_id,
            title="Roundtrip Test Entry",
            content_format="latex",
            author_id=author_id,
            author_handle="ivan",
            created_at=created_at,
            tags=["physics", "cosmology"],
            summary="Testing the roundtrip.",
            license="MIT",
            layout_hint="paper",
        )
        parsed = parse_entry_yaml(yaml_str)
        assert parsed["title"] == "Roundtrip Test Entry"
        assert parsed["content_format"] == "latex"
        assert parsed["tags"] == ["physics", "cosmology"]
        assert parsed["summary"] == "Testing the roundtrip."
        assert parsed["license"] == "MIT"
        assert parsed["layout_hint"] == "paper"
        # entry_id should have ent_ prefix
        assert parsed["entry_id"].startswith("ent_")
        assert str(entry_id) in parsed["entry_id"]

    def test_parse_minimal_yaml(self) -> None:
        """Parse YAML with only required fields succeeds."""
        yaml_str = yaml.dump({
            "entry_id": f"ent_{uuid4()}",
            "schema_version": 1,
            "title": "Parsed Minimal",
            "content_format": "markdown",
            "author": {"id": str(uuid4()), "name": "parser-test"},
            "created_at": "2026-03-15T12:00:00+00:00",
        })
        parsed = parse_entry_yaml(yaml_str)
        assert parsed["title"] == "Parsed Minimal"
        assert parsed["content_format"] == "markdown"

    def test_parse_invalid_yaml_raises(self) -> None:
        """Malformed YAML raises an appropriate error."""
        with pytest.raises(Exception):
            parse_entry_yaml("not: valid: yaml: [unterminated")

    def test_parse_missing_required_field_raises(self) -> None:
        """YAML missing 'title' field raises an error."""
        yaml_str = yaml.dump({
            "entry_id": f"ent_{uuid4()}",
            "schema_version": 1,
            "content_format": "markdown",
            "author": {"id": str(uuid4()), "name": "test"},
            "created_at": "2026-03-15T12:00:00+00:00",
        })
        with pytest.raises(Exception):
            parse_entry_yaml(yaml_str)

    def test_parse_preserves_unicode(self) -> None:
        """YAML with unicode characters parses correctly."""
        entry_id = uuid4()
        yaml_str = generate_entry_yaml(
            entry_id=entry_id,
            title="\u91cf\u5b50\u529b\u5b66\u306e\u57fa\u790e",
            content_format="markdown",
            author_id=uuid4(),
            author_handle="unicode-test",
            created_at=datetime.now(tz=timezone.utc),
            summary="\u6982\u8981: \u91cf\u5b50\u529b\u5b66\u306e\u57fa\u672c\u7684\u306a\u6982\u5ff5",
        )
        parsed = parse_entry_yaml(yaml_str)
        assert parsed["title"] == "\u91cf\u5b50\u529b\u5b66\u306e\u57fa\u790e"
        assert "\u91cf\u5b50\u529b\u5b66" in parsed["summary"]
