# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for search tool schemas (NEV-133).

Tests pure validation and data transformation logic. No database or HTTP.
All tests should FAIL against the stubs.
"""

from __future__ import annotations

from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# SearchResultItem schema
# ---------------------------------------------------------------------------


class TestSearchResultItemSchema:
    """Tests for the SearchResultItem schema (single search result)."""

    def test_construction_with_all_fields(self) -> None:
        """SearchResultItem can be constructed with all required fields."""
        from phiacta.tools.search.schemas import SearchResultItem

        entry_id = uuid4()
        item = SearchResultItem(
            entry_id=entry_id,
            title="Test Entry",
            summary="A brief summary",
            layout_hint="article",
            rank=0.85,
        )
        assert item.entry_id == entry_id
        assert item.title == "Test Entry"
        assert item.summary == "A brief summary"
        assert item.layout_hint == "article"
        assert item.rank == 0.85

    def test_summary_can_be_none(self) -> None:
        """SearchResultItem.summary accepts None (entries may have no summary)."""
        from phiacta.tools.search.schemas import SearchResultItem

        item = SearchResultItem(
            entry_id=uuid4(),
            title="No Summary Entry",
            summary=None,
            layout_hint="article",
            rank=0.5,
        )
        assert item.summary is None

    def test_layout_hint_can_be_none(self) -> None:
        """SearchResultItem.layout_hint accepts None."""
        from phiacta.tools.search.schemas import SearchResultItem

        item = SearchResultItem(
            entry_id=uuid4(),
            title="No Layout Entry",
            summary=None,
            layout_hint=None,
            rank=0.3,
        )
        assert item.layout_hint is None

    def test_rank_is_float(self) -> None:
        """SearchResultItem.rank is a float."""
        from phiacta.tools.search.schemas import SearchResultItem

        item = SearchResultItem(
            entry_id=uuid4(),
            title="Rank Test",
            summary=None,
            layout_hint=None,
            rank=0.123456,
        )
        assert isinstance(item.rank, float)
        assert item.rank == pytest.approx(0.123456)

    def test_entry_id_is_uuid(self) -> None:
        """SearchResultItem.entry_id must be a UUID."""
        from phiacta.tools.search.schemas import SearchResultItem

        eid = uuid4()
        item = SearchResultItem(
            entry_id=eid,
            title="UUID Test",
            summary=None,
            layout_hint=None,
            rank=0.5,
        )
        assert item.entry_id == eid

    def test_from_attributes_mode(self) -> None:
        """SearchResultItem should support model_validate with from_attributes=True.

        This is needed because the repository returns ORM-like tuples.
        """
        from phiacta.tools.search.schemas import SearchResultItem

        eid = uuid4()
        data = {
            "entry_id": eid,
            "title": "Attrs Test",
            "summary": "Summary from attrs",
            "layout_hint": "paper",
            "rank": 0.75,
        }
        item = SearchResultItem.model_validate(data)
        assert item.entry_id == eid
        assert item.title == "Attrs Test"
        assert item.summary == "Summary from attrs"
        assert item.layout_hint == "paper"
        assert item.rank == 0.75

    def test_serialization_to_dict(self) -> None:
        """SearchResultItem serializes to dict with correct field names."""
        from phiacta.tools.search.schemas import SearchResultItem

        eid = uuid4()
        item = SearchResultItem(
            entry_id=eid,
            title="Serialize Test",
            summary="A summary",
            layout_hint="article",
            rank=0.9,
        )
        d = item.model_dump(mode="json")
        assert d["entry_id"] == str(eid)
        assert d["title"] == "Serialize Test"
        assert d["summary"] == "A summary"
        assert d["layout_hint"] == "article"
        assert d["rank"] == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# SearchResponse schema
# ---------------------------------------------------------------------------


class TestSearchResponseSchema:
    """Tests for the SearchResponse schema (paginated search results with version_id)."""

    def test_construction_with_all_fields(self) -> None:
        """SearchResponse can be constructed with items, total, limit, offset, version_id."""
        from phiacta.tools.search.schemas import SearchResponse, SearchResultItem

        vid = uuid4()
        items = [
            SearchResultItem(
                entry_id=uuid4(),
                title="Result 1",
                summary=None,
                layout_hint=None,
                rank=0.9,
            ),
        ]
        resp = SearchResponse(
            items=items,
            total=1,
            limit=50,
            offset=0,
            version_id=vid,
        )
        assert len(resp.items) == 1
        assert resp.total == 1
        assert resp.limit == 50
        assert resp.offset == 0
        assert resp.version_id == vid

    def test_has_more_true_when_more_results(self) -> None:
        """has_more is True when offset + limit < total."""
        from phiacta.tools.search.schemas import SearchResponse

        resp = SearchResponse(
            items=[],
            total=100,
            limit=10,
            offset=0,
            version_id=uuid4(),
        )
        assert resp.has_more is True

    def test_has_more_false_when_no_more_results(self) -> None:
        """has_more is False when offset + limit >= total."""
        from phiacta.tools.search.schemas import SearchResponse

        resp = SearchResponse(
            items=[],
            total=10,
            limit=50,
            offset=0,
            version_id=uuid4(),
        )
        assert resp.has_more is False

    def test_has_more_false_at_exact_boundary(self) -> None:
        """has_more is False when offset + limit == total exactly."""
        from phiacta.tools.search.schemas import SearchResponse

        resp = SearchResponse(
            items=[],
            total=50,
            limit=50,
            offset=0,
            version_id=uuid4(),
        )
        assert resp.has_more is False

    def test_has_more_true_at_boundary_minus_one(self) -> None:
        """has_more is True when offset + limit == total - 1."""
        from phiacta.tools.search.schemas import SearchResponse

        resp = SearchResponse(
            items=[],
            total=51,
            limit=50,
            offset=0,
            version_id=uuid4(),
        )
        assert resp.has_more is True

    def test_empty_items_with_zero_total(self) -> None:
        """SearchResponse with empty items and total=0 is valid."""
        from phiacta.tools.search.schemas import SearchResponse

        resp = SearchResponse(
            items=[],
            total=0,
            limit=50,
            offset=0,
            version_id=uuid4(),
        )
        assert resp.items == []
        assert resp.total == 0
        assert resp.has_more is False

    def test_version_id_is_uuid(self) -> None:
        """SearchResponse.version_id must be a UUID."""
        from phiacta.tools.search.schemas import SearchResponse

        vid = uuid4()
        resp = SearchResponse(
            items=[],
            total=0,
            limit=50,
            offset=0,
            version_id=vid,
        )
        assert resp.version_id == vid

    def test_serialization_includes_has_more(self) -> None:
        """Serialized SearchResponse includes the computed has_more field."""
        from phiacta.tools.search.schemas import SearchResponse

        resp = SearchResponse(
            items=[],
            total=100,
            limit=10,
            offset=0,
            version_id=uuid4(),
        )
        d = resp.model_dump(mode="json")
        assert "has_more" in d
        assert d["has_more"] is True

    def test_serialization_includes_version_id(self) -> None:
        """Serialized SearchResponse includes the version_id field."""
        from phiacta.tools.search.schemas import SearchResponse

        vid = uuid4()
        resp = SearchResponse(
            items=[],
            total=0,
            limit=50,
            offset=0,
            version_id=vid,
        )
        d = resp.model_dump(mode="json")
        assert d["version_id"] == str(vid)

    def test_multiple_items_serialization(self) -> None:
        """SearchResponse with multiple items serializes all of them correctly."""
        from phiacta.tools.search.schemas import SearchResponse, SearchResultItem

        items = [
            SearchResultItem(
                entry_id=uuid4(),
                title=f"Entry {i}",
                summary=f"Summary {i}" if i % 2 == 0 else None,
                layout_hint="article" if i % 2 == 0 else None,
                rank=1.0 - (i * 0.1),
            )
            for i in range(5)
        ]
        resp = SearchResponse(
            items=items,
            total=10,
            limit=5,
            offset=0,
            version_id=uuid4(),
        )
        d = resp.model_dump(mode="json")
        assert len(d["items"]) == 5
        assert d["total"] == 10
        assert d["has_more"] is True
        # Verify items are properly serialized
        for i, item in enumerate(d["items"]):
            assert item["title"] == f"Entry {i}"
            assert isinstance(item["entry_id"], str)
            assert isinstance(item["rank"], float)
