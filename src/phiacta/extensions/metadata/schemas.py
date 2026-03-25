# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Pydantic schemas for the metadata extension."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MetadataSetRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    summary: str | None = None


class MetadataUpdateRequest(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    summary: str | None = None


class MetadataResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    entry_id: UUID
    title: str
    summary: str | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
