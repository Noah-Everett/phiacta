# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for search tool schemas — entry_id + rank + optional metadata."""

from __future__ import annotations

from uuid import uuid4

import pytest


class TestSearchResultItemSchema:
    def test_construction_minimal(self) -> None:
        from phiacta.tools.search.schemas import SearchResultItem
        item = SearchResultItem(entry_id=uuid4(), rank=0.85)
        assert item.rank == 0.85
        assert item.title is None
        assert item.summary is None
        assert item.entry_type is None

    def test_construction_with_metadata(self) -> None:
        from phiacta.tools.search.schemas import SearchResultItem
        item = SearchResultItem(entry_id=uuid4(), rank=0.9, title="Test", summary="Sum", entry_type="claim")
        assert item.title == "Test"
        assert item.entry_type == "claim"

    def test_serialization_without_metadata(self) -> None:
        from phiacta.tools.search.schemas import SearchResultItem
        d = SearchResultItem(entry_id=uuid4(), rank=0.9).model_dump(mode="json")
        assert d["title"] is None
        assert "layout_hint" not in d


class TestSearchResponseSchema:
    def test_construction(self) -> None:
        from phiacta.tools.search.schemas import SearchResponse, SearchResultItem
        items = [SearchResultItem(entry_id=uuid4(), rank=0.9)]
        resp = SearchResponse(items=items, limit=50, has_more=False, next_cursor=None, version_id=uuid4())
        assert len(resp.items) == 1
        assert resp.has_more is False
        assert resp.next_cursor is None

    def test_has_more(self) -> None:
        from phiacta.tools.search.schemas import SearchResponse
        resp = SearchResponse(items=[], limit=10, has_more=True, next_cursor="abc", version_id=uuid4())
        assert resp.has_more is True
        assert resp.next_cursor == "abc"
