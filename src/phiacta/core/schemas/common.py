# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from pydantic import BaseModel, computed_field


class PaginatedResponse[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_more(self) -> bool:
        return self.offset + self.limit < self.total


class ErrorResponse(BaseModel):
    detail: str
