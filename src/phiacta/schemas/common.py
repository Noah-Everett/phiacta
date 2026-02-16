# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from pydantic import BaseModel


class PaginatedResponse[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class ErrorResponse(BaseModel):
    detail: str
