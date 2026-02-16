# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from phiacta.schemas.claim import ClaimResponse


class SearchRequest(BaseModel):
    query: str
    namespace_id: UUID | None = None
    claim_type: str | None = None
    limit: int = 20
    offset: int = 0


class SearchResult(BaseModel):
    claim: ClaimResponse
    rank: float


class SearchResponse(BaseModel):
    results: list[SearchResult]
    total: int
    query: str
