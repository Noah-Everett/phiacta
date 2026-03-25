# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Search tool schemas."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from phiacta.core.schemas.common import PaginatedResponse


class SearchResultItem(BaseModel):
    entry_id: UUID
    title: str | None
    summary: str | None
    entry_type: str | None
    rank: float


class SearchResponse(PaginatedResponse[SearchResultItem]):
    version_id: UUID | None
