# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Search tool schemas."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from phiacta.core.pagination import CursorPage


class SearchResultItem(BaseModel):
    entry_id: UUID
    rank: float
    title: str | None = None
    summary: str | None = None
    entry_type: str | None = None


class SearchResponse(CursorPage[SearchResultItem]):
    version_id: UUID | None
