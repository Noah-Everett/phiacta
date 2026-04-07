# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class CompileRequest(BaseModel):
    entry_id: UUID


class CompileResponse(BaseModel):
    success: bool
    log: str
    pdf_path: str | None = None
