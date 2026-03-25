# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Pydantic schemas for the types extension."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TypeSetRequest(BaseModel):
    entry_type: str = Field(min_length=1, max_length=100)


class TypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    entry_id: UUID
    entry_type: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime
