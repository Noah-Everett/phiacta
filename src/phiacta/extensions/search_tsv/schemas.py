# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Pydantic schemas for the search_tsv extension endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SearchTsvResponse(BaseModel):
    """Response schema for GET /v1/extensions/search_tsv/{entry_id}."""

    model_config = ConfigDict(from_attributes=True)

    entry_id: UUID
    version_id: UUID
    tsv: str
    computed_at: datetime


class SearchTsvVersionResponse(BaseModel):
    """Response schema for GET /v1/extensions/search_tsv/version."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    view_type: str
    version: str
    status: str
    parameters: dict[str, Any]
