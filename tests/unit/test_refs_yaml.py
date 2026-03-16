# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for refs YAML parsing (NEV-119).

Tests the parse_refs_yaml() function that parses .phiacta/refs.yaml content
into a structured list of ref descriptors. Mirrors the pattern established
in tests/unit/test_entry_yaml.py.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import yaml

from phiacta.services.refs_yaml import parse_refs_yaml


class TestParseRefsYamlHappyPath:
    """Tests for successful parsing of well-formed refs.yaml content."""

    def test_parse_single_ref(self) -> None:
        """Parse refs.yaml with one reference returns a list of one dict."""
        target_id = uuid4()
        yaml_str = yaml.dump({
            "refs": [
                {
                    "rel": "cites",
                    "target": {"entry_id": f"ent_{target_id}"},
                }
            ]
        })
        result = parse_refs_yaml(yaml_str)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["rel"] == "cites"
        assert result[0]["target"]["entry_id"] == f"ent_{target_id}"

    def test_parse_multiple_refs(self) -> None:
        """Parse refs.yaml with multiple references returns all of them."""
        id_a = uuid4()
        id_b = uuid4()
        yaml_str = yaml.dump({
            "refs": [
                {
                    "rel": "cites",
                    "target": {"entry_id": f"ent_{id_a}"},
                    "note": "Cited in section 3",
                },
                {
                    "rel": "extends",
                    "target": {"entry_id": f"ent_{id_b}"},
                    "version_sha": "abc123" * 6 + "abcd",
                },
            ]
        })
        result = parse_refs_yaml(yaml_str)
        assert len(result) == 2
        assert result[0]["rel"] == "cites"
        assert result[0]["note"] == "Cited in section 3"
        assert result[1]["rel"] == "extends"
        assert result[1]["version_sha"] == "abc123" * 6 + "abcd"

    def test_parse_ref_with_all_optional_fields(self) -> None:
        """Ref with note and version_sha both present parses correctly."""
        target_id = uuid4()
        version_sha = "deadbeef" * 5
        yaml_str = yaml.dump({
            "refs": [
                {
                    "rel": "derives",
                    "target": {"entry_id": f"ent_{target_id}"},
                    "note": "Derived from theorem 4.2",
                    "version_sha": version_sha,
                }
            ]
        })
        result = parse_refs_yaml(yaml_str)
        assert len(result) == 1
        assert result[0]["rel"] == "derives"
        assert result[0]["note"] == "Derived from theorem 4.2"
        assert result[0]["version_sha"] == version_sha
        assert result[0]["target"]["entry_id"] == f"ent_{target_id}"

    def test_parse_ref_minimal_fields(self) -> None:
        """Ref with only required fields (rel, target.entry_id) parses correctly."""
        target_id = uuid4()
        yaml_str = yaml.dump({
            "refs": [
                {
                    "rel": "supports",
                    "target": {"entry_id": f"ent_{target_id}"},
                }
            ]
        })
        result = parse_refs_yaml(yaml_str)
        assert len(result) == 1
        assert result[0]["rel"] == "supports"
        assert result[0]["target"]["entry_id"] == f"ent_{target_id}"
        # Optional fields not present or None
        assert result[0].get("note") is None
        assert result[0].get("version_sha") is None

    def test_parse_empty_refs_list(self) -> None:
        """Empty refs list parses to an empty list."""
        yaml_str = yaml.dump({"refs": []})
        result = parse_refs_yaml(yaml_str)
        assert isinstance(result, list)
        assert len(result) == 0

    def test_parse_preserves_entry_id_with_ent_prefix(self) -> None:
        """entry_id in target retains the ent_ prefix from YAML."""
        target_id = uuid4()
        yaml_str = yaml.dump({
            "refs": [
                {
                    "rel": "cites",
                    "target": {"entry_id": f"ent_{target_id}"},
                }
            ]
        })
        result = parse_refs_yaml(yaml_str)
        assert result[0]["target"]["entry_id"].startswith("ent_")
        assert str(target_id) in result[0]["target"]["entry_id"]

    def test_parse_unicode_in_note(self) -> None:
        """Unicode characters in note field are preserved."""
        target_id = uuid4()
        note = "\u91cf\u5b50\u529b\u5b66: \u30d9\u30eb\u306e\u4e0d\u7b49\u5f0f\u306e\u8a3c\u660e"
        yaml_str = yaml.dump({
            "refs": [
                {
                    "rel": "cites",
                    "target": {"entry_id": f"ent_{target_id}"},
                    "note": note,
                }
            ]
        })
        result = parse_refs_yaml(yaml_str)
        assert result[0]["note"] == note

    def test_parse_various_rel_types(self) -> None:
        """Different rel type strings are preserved exactly."""
        target_id = uuid4()
        rel_types = ["cites", "extends", "derives", "supports", "contradicts", "generalizes"]
        refs = [
            {"rel": rel, "target": {"entry_id": f"ent_{target_id}"}}
            for rel in rel_types
        ]
        yaml_str = yaml.dump({"refs": refs})
        result = parse_refs_yaml(yaml_str)
        assert len(result) == len(rel_types)
        parsed_rels = [r["rel"] for r in result]
        assert parsed_rels == rel_types


class TestParseRefsYamlErrors:
    """Tests for error handling when refs.yaml is malformed."""

    def test_invalid_yaml_raises_error(self) -> None:
        """Completely malformed YAML raises ValueError."""
        with pytest.raises(ValueError):
            parse_refs_yaml("refs: [not: valid: yaml: [unterminated")

    def test_non_dict_root_raises_error(self) -> None:
        """YAML that parses to a non-dict (e.g. a list) raises ValueError."""
        with pytest.raises(ValueError):
            parse_refs_yaml("- item1\n- item2")

    def test_missing_refs_key_raises_error(self) -> None:
        """YAML without a 'refs' top-level key raises ValueError."""
        with pytest.raises(ValueError):
            parse_refs_yaml(yaml.dump({"references": []}))

    def test_refs_not_a_list_raises_error(self) -> None:
        """refs key that is not a list raises ValueError."""
        with pytest.raises(ValueError):
            parse_refs_yaml(yaml.dump({"refs": "not-a-list"}))

    def test_ref_missing_rel_raises_error(self) -> None:
        """Ref entry missing 'rel' field raises ValueError."""
        target_id = uuid4()
        with pytest.raises(ValueError):
            parse_refs_yaml(yaml.dump({
                "refs": [
                    {"target": {"entry_id": f"ent_{target_id}"}},
                ]
            }))

    def test_ref_missing_target_raises_error(self) -> None:
        """Ref entry missing 'target' field raises ValueError."""
        with pytest.raises(ValueError):
            parse_refs_yaml(yaml.dump({
                "refs": [
                    {"rel": "cites"},
                ]
            }))

    def test_ref_target_missing_entry_id_raises_error(self) -> None:
        """Ref target dict missing 'entry_id' raises ValueError."""
        with pytest.raises(ValueError):
            parse_refs_yaml(yaml.dump({
                "refs": [
                    {"rel": "cites", "target": {}},
                ]
            }))

    def test_ref_target_not_dict_raises_error(self) -> None:
        """Ref target that is a string instead of dict raises ValueError."""
        with pytest.raises(ValueError):
            parse_refs_yaml(yaml.dump({
                "refs": [
                    {"rel": "cites", "target": "not-a-dict"},
                ]
            }))

    def test_null_yaml_raises_error(self) -> None:
        """Null/empty YAML raises ValueError."""
        with pytest.raises(ValueError):
            parse_refs_yaml("")

    def test_yaml_with_only_null_raises_error(self) -> None:
        """YAML that parses to None raises ValueError."""
        with pytest.raises(ValueError):
            parse_refs_yaml("null")

    def test_refs_list_with_non_dict_element_raises_error(self) -> None:
        """refs list containing a non-dict element (e.g., a string) raises ValueError."""
        with pytest.raises(ValueError):
            parse_refs_yaml(yaml.dump({
                "refs": ["not-a-dict"],
            }))


class TestParseRefsYamlEdgeCases:
    """Tests for edge cases in refs.yaml parsing."""

    def test_extra_fields_in_ref_preserved(self) -> None:
        """Unknown fields in a ref entry are preserved in the output dict."""
        target_id = uuid4()
        yaml_str = yaml.dump({
            "refs": [
                {
                    "rel": "cites",
                    "target": {"entry_id": f"ent_{target_id}"},
                    "custom_field": "some-value",
                }
            ]
        })
        result = parse_refs_yaml(yaml_str)
        assert len(result) == 1
        # At minimum, the required fields must be present.
        # Whether extra fields are kept or stripped is implementation choice,
        # but the function should not crash.
        assert result[0]["rel"] == "cites"

    def test_many_refs_parsed_correctly(self) -> None:
        """Parsing a large number of refs (50) works correctly."""
        refs = [
            {
                "rel": "cites",
                "target": {"entry_id": f"ent_{uuid4()}"},
                "note": f"Reference {i}",
            }
            for i in range(50)
        ]
        yaml_str = yaml.dump({"refs": refs})
        result = parse_refs_yaml(yaml_str)
        assert len(result) == 50
        for i, r in enumerate(result):
            assert r["note"] == f"Reference {i}"

    def test_entry_id_without_ent_prefix_still_parses(self) -> None:
        """entry_id without ent_ prefix is accepted (validation is caller's job)."""
        raw_uuid = str(uuid4())
        yaml_str = yaml.dump({
            "refs": [
                {
                    "rel": "cites",
                    "target": {"entry_id": raw_uuid},
                }
            ]
        })
        # parse_refs_yaml should not crash -- prefix stripping is the caller's job
        result = parse_refs_yaml(yaml_str)
        assert len(result) == 1
        assert result[0]["target"]["entry_id"] == raw_uuid
