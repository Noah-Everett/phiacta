# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from pydantic import BaseModel

from phiacta.schemas.entry import EntryResponse


class SearchRequest(BaseModel):
    query: str
    layout_hint: str | None = None
    limit: int = 20
    offset: int = 0


class SearchResult(BaseModel):
    entry: EntryResponse
    rank: float


class SearchResponse(BaseModel):
    results: list[SearchResult]
    total: int
    query: str
