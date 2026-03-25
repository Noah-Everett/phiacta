# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import uuid4

import pytest


class TestSearchResultItemSchema:
    def test_construction_with_all_fields(self) -> None:
        from phiacta.tools.search.schemas import SearchResultItem
        item = SearchResultItem(entry_id=uuid4(), title="Test", summary="Sum", entry_type="article", rank=0.85)
        assert item.title == "Test"
        assert item.entry_type == "article"

    def test_entry_type_can_be_none(self) -> None:
        from phiacta.tools.search.schemas import SearchResultItem
        item = SearchResultItem(entry_id=uuid4(), title="T", summary=None, entry_type=None, rank=0.3)
        assert item.entry_type is None

    def test_serialization(self) -> None:
        from phiacta.tools.search.schemas import SearchResultItem
        eid = uuid4()
        item = SearchResultItem(entry_id=eid, title="S", summary="A", entry_type="article", rank=0.9)
        d = item.model_dump(mode="json")
        assert d["entry_type"] == "article"
        assert "layout_hint" not in d


class TestSearchResponseSchema:
    def test_construction(self) -> None:
        from phiacta.tools.search.schemas import SearchResponse, SearchResultItem
        items = [SearchResultItem(entry_id=uuid4(), title="R", summary=None, entry_type=None, rank=0.9)]
        resp = SearchResponse(items=items, total=1, limit=50, offset=0, version_id=uuid4())
        assert len(resp.items) == 1

    def test_has_more(self) -> None:
        from phiacta.tools.search.schemas import SearchResponse
        resp = SearchResponse(items=[], total=100, limit=10, offset=0, version_id=uuid4())
        assert resp.has_more is True
