# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for tags extension schemas and normalization (NEV-131).

Tests pure validation and data transformation logic. No database or HTTP.
All tests should FAIL against the stubs.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestTagSetRequestSchema:
    """Tests for the TagSetRequest schema (Pydantic model for PUT body)."""

    def test_valid_tags(self) -> None:
        """TagSetRequest with a normal list of tags is valid."""
        from phiacta.extensions.tags.schemas import TagSetRequest

        req = TagSetRequest(tags=["physics", "mathematics", "cosmology"])
        assert req.tags == ["physics", "mathematics", "cosmology"]

    def test_empty_list_is_valid(self) -> None:
        """TagSetRequest with an empty list is valid (clears all tags)."""
        from phiacta.extensions.tags.schemas import TagSetRequest

        req = TagSetRequest(tags=[])
        assert req.tags == []

    def test_single_tag(self) -> None:
        """TagSetRequest with a single tag is valid."""
        from phiacta.extensions.tags.schemas import TagSetRequest

        req = TagSetRequest(tags=["solo"])
        assert req.tags == ["solo"]

    def test_tag_over_200_chars_invalid(self) -> None:
        """TagSetRequest rejects tags longer than 200 characters."""
        from phiacta.extensions.tags.schemas import TagSetRequest

        with pytest.raises(Exception):
            TagSetRequest(tags=["a" * 201])

    def test_tag_exactly_200_chars_valid(self) -> None:
        """TagSetRequest accepts tags of exactly 200 characters."""
        from phiacta.extensions.tags.schemas import TagSetRequest

        req = TagSetRequest(tags=["a" * 200])
        assert len(req.tags[0]) == 200

    def test_empty_string_tag_invalid(self) -> None:
        """TagSetRequest rejects empty string tags."""
        from phiacta.extensions.tags.schemas import TagSetRequest

        with pytest.raises(Exception):
            TagSetRequest(tags=["valid", ""])

    def test_more_than_50_tags_invalid(self) -> None:
        """TagSetRequest rejects more than 50 tags."""
        from phiacta.extensions.tags.schemas import TagSetRequest

        with pytest.raises(Exception):
            TagSetRequest(tags=[f"tag-{i}" for i in range(51)])

    def test_exactly_50_tags_valid(self) -> None:
        """TagSetRequest accepts exactly 50 tags."""
        from phiacta.extensions.tags.schemas import TagSetRequest

        req = TagSetRequest(tags=[f"tag-{i}" for i in range(50)])
        assert len(req.tags) == 50

    def test_tag_with_comma_invalid(self) -> None:
        """TagSetRequest rejects tags containing commas."""
        from phiacta.extensions.tags.schemas import TagSetRequest

        with pytest.raises(Exception):
            TagSetRequest(tags=["physics,math"])


class TestTagResponseSchema:
    """Tests for the TagResponse schema (Pydantic model for response items)."""

    def test_construction_from_attributes(self) -> None:
        """TagResponse can be constructed with tag, created_by, created_at."""
        from datetime import datetime, timezone
        from uuid import uuid4

        from phiacta.extensions.tags.schemas import TagResponse

        now = datetime.now(tz=timezone.utc)
        user_id = uuid4()
        tr = TagResponse(tag="physics", created_by=user_id, created_at=now)
        assert tr.tag == "physics"
        assert tr.created_by == user_id
        assert tr.created_at == now

    def test_tag_list_response_shape(self) -> None:
        """TagListResponse includes entry_id and a list of TagResponse objects."""
        from datetime import datetime, timezone
        from uuid import uuid4

        from phiacta.extensions.tags.schemas import TagListResponse, TagResponse

        entry_id = uuid4()
        user_id = uuid4()
        now = datetime.now(tz=timezone.utc)
        tags = [
            TagResponse(tag="physics", created_by=user_id, created_at=now),
            TagResponse(tag="math", created_by=user_id, created_at=now),
        ]
        tlr = TagListResponse(entry_id=entry_id, tags=tags)
        assert tlr.entry_id == entry_id
        assert len(tlr.tags) == 2
        assert tlr.tags[0].tag == "physics"


class TestEntryTagItemSchema:
    """Tests for the EntryTagItem schema (response items for find-by-tags)."""

    def test_entry_tag_item_construction(self) -> None:
        """EntryTagItem has entry_id + optional metadata."""
        from uuid import uuid4

        from phiacta.extensions.tags.schemas import EntryTagItem

        entry_id = uuid4()
        item = EntryTagItem(entry_id=entry_id)
        assert item.entry_id == entry_id
        assert item.title is None

    def test_entry_tag_item_with_metadata(self) -> None:
        """EntryTagItem accepts optional title/summary/entry_type."""
        from uuid import uuid4

        from phiacta.extensions.tags.schemas import EntryTagItem

        item = EntryTagItem(entry_id=uuid4(), title="Test", entry_type="claim")
        assert item.title == "Test"
        assert item.entry_type == "claim"


# ---------------------------------------------------------------------------
# Tag normalization tests
# ---------------------------------------------------------------------------


class TestTagNormalization:
    """Tests for the normalize_tags utility function."""

    def test_lowercase_conversion(self) -> None:
        """Tags are converted to lowercase."""
        from phiacta.extensions.tags.service import normalize_tags

        result = normalize_tags(["Physics", "MATH", "Theory"])
        assert result == ["physics", "math", "theory"]

    def test_whitespace_stripping(self) -> None:
        """Leading and trailing whitespace is stripped."""
        from phiacta.extensions.tags.service import normalize_tags

        result = normalize_tags(["  physics  ", " math "])
        assert "physics" in result
        assert "math" in result

    def test_deduplication_after_normalization(self) -> None:
        """Duplicates after lowercasing and stripping are removed."""
        from phiacta.extensions.tags.service import normalize_tags

        result = normalize_tags(["physics", "Physics", "PHYSICS", " physics "])
        assert result == ["physics"]

    def test_empty_after_strip_filtered(self) -> None:
        """Tags that become empty after stripping are removed."""
        from phiacta.extensions.tags.service import normalize_tags

        result = normalize_tags(["valid", "   ", "\t", ""])
        assert result == ["valid"]

    def test_comma_rejection(self) -> None:
        """Tags containing commas raise ValueError."""
        from phiacta.extensions.tags.service import normalize_tags

        with pytest.raises(ValueError, match="comma"):
            normalize_tags(["physics,math"])

    def test_preserves_order_of_first_occurrence(self) -> None:
        """Deduplication preserves the order of first occurrence."""
        from phiacta.extensions.tags.service import normalize_tags

        result = normalize_tags(["beta", "alpha", "beta", "gamma", "alpha"])
        assert result == ["beta", "alpha", "gamma"]

    def test_empty_input(self) -> None:
        """Empty input returns empty list."""
        from phiacta.extensions.tags.service import normalize_tags

        result = normalize_tags([])
        assert result == []

    def test_mixed_normalization(self) -> None:
        """Combined case: mixed case, whitespace, duplicates, empty strings."""
        from phiacta.extensions.tags.service import normalize_tags

        result = normalize_tags([
            "  Physics  ",
            "physics",
            "",
            "  MATH  ",
            "   ",
            "math",
            "unique",
        ])
        assert result == ["physics", "math", "unique"]
