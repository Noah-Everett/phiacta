# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Search tool schemas — request validation and response models."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from phiacta.core.schemas.common import PaginatedResponse


class SearchResultItem(BaseModel):
    """A single search result — entry metadata plus relevance rank."""

    entry_id: UUID
    title: str
    summary: str | None
    layout_hint: str | None
    rank: float


class SearchResponse(PaginatedResponse[SearchResultItem]):
    """Paginated search results with version metadata."""

    version_id: UUID | None
