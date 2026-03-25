# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for entry.yaml after entry minimization."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import yaml

from phiacta.core.services.entry_yaml import generate_entry_yaml, parse_entry_yaml


class TestGenerateEntryYaml:
    def test_generates_identity_fields(self) -> None:
        entry_id, author_id = uuid4(), uuid4()
        result = generate_entry_yaml(entry_id=entry_id, schema_version=1, author_id=author_id, author_name="Jane", created_at=datetime(2026, 3, 1, tzinfo=UTC))
        parsed = yaml.safe_load(result)
        assert parsed["entry_id"] == f"ent_{entry_id}"
        assert parsed["schema_version"] == 1
        assert parsed["author"]["name"] == "Jane"

    def test_does_not_include_title(self) -> None:
        result = generate_entry_yaml(entry_id=uuid4(), author_id=uuid4(), author_name="T", created_at=datetime.now(UTC))
        assert "title" not in yaml.safe_load(result)

    def test_does_not_include_summary(self) -> None:
        assert "summary" not in yaml.safe_load(generate_entry_yaml(entry_id=uuid4(), author_id=uuid4(), author_name="T", created_at=datetime.now(UTC)))

    def test_does_not_include_content_format(self) -> None:
        assert "content_format" not in yaml.safe_load(generate_entry_yaml(entry_id=uuid4(), author_id=uuid4(), author_name="T", created_at=datetime.now(UTC)))

    def test_does_not_include_layout_hint(self) -> None:
        assert "layout_hint" not in yaml.safe_load(generate_entry_yaml(entry_id=uuid4(), author_id=uuid4(), author_name="T", created_at=datetime.now(UTC)))

    def test_does_not_include_license(self) -> None:
        assert "license" not in yaml.safe_load(generate_entry_yaml(entry_id=uuid4(), author_id=uuid4(), author_name="T", created_at=datetime.now(UTC)))


class TestParseEntryYaml:
    def test_roundtrip(self) -> None:
        entry_id, author_id = uuid4(), uuid4()
        yaml_str = generate_entry_yaml(entry_id=entry_id, author_id=author_id, author_name="Roundtrip", created_at=datetime(2026, 6, 15, tzinfo=UTC))
        parsed = parse_entry_yaml(yaml_str)
        assert parsed["entry_id"] == entry_id
        assert parsed["author_id"] == author_id

    def test_forwards_compat_ignores_extra_fields(self) -> None:
        entry_id = uuid4()
        yaml_content = yaml.dump({"entry_id": f"ent_{entry_id}", "schema_version": 1, "author": {"id": f"usr_{uuid4()}", "name": "T"}, "created_at": "2026-01-01T00:00:00", "extra": "ignored"})
        parsed = parse_entry_yaml(yaml_content)
        assert parsed["entry_id"] == entry_id

    def test_raises_on_missing_entry_id(self) -> None:
        with pytest.raises((ValueError, KeyError)):
            parse_entry_yaml(yaml.dump({"schema_version": 1, "author": {"id": f"usr_{uuid4()}", "name": "T"}, "created_at": "2026-01-01"}))

    def test_raises_on_invalid_yaml(self) -> None:
        with pytest.raises((ValueError, yaml.YAMLError)):
            parse_entry_yaml(": invalid: yaml: {{")
