# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Cursor-based pagination utilities (PHI-193).

Provides:
- ``CursorPage[T]``: Universal paginated response model
- ``encode_cursor`` / ``decode_cursor``: Opaque cursor encoding
- ``keyset_condition``: SQLAlchemy WHERE clause for keyset pagination
- ``build_cursor_page``: Helper to build CursorPage from limit+1 results
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import BooleanClauseList, Column, and_, or_


class CursorPage[T](BaseModel):
    """Universal cursor-based paginated response."""

    items: list[T]
    limit: int
    has_more: bool
    next_cursor: str | None


def encode_cursor(values: dict) -> str:
    """Encode cursor values to an opaque base64url string (no padding)."""
    raw = json.dumps(values, separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def decode_cursor(cursor: str) -> dict:
    """Decode an opaque cursor string back to a dict of values.

    Raises ``ValueError`` on any invalid input.
    """
    if not cursor:
        raise ValueError("Empty cursor")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded)
    except Exception as exc:
        raise ValueError(f"Invalid cursor encoding: {exc}") from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid cursor JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"Cursor must be a JSON object, got {type(parsed).__name__}")
    return parsed


def keyset_condition(
    sort_column: Column,
    id_column: Column,
    sort_value: Any,
    cursor_id: Any,
    descending: bool = True,
) -> BooleanClauseList:
    """Build a SQLAlchemy WHERE clause for keyset pagination.

    For DESC: ``(sort_col < val) OR (sort_col == val AND id < cursor_id)``
    For ASC:  ``(sort_col > val) OR (sort_col == val AND id > cursor_id)``
    """
    if descending:
        return or_(
            sort_column < sort_value,
            and_(sort_column == sort_value, id_column < cursor_id),
        )
    else:
        return or_(
            sort_column > sort_value,
            and_(sort_column == sort_value, id_column > cursor_id),
        )


def build_keyset_cursor(
    sort_col_name: str,
    sort_order: str,
    sort_value: Any,
    item_id: UUID,
) -> str:
    """Build and encode a keyset cursor from the last item in a page."""
    # Serialize datetime to ISO format string
    if isinstance(sort_value, datetime):
        sort_value = sort_value.isoformat()
    return encode_cursor({
        "s": sort_col_name,
        "o": sort_order,
        "v": sort_value,
        "id": str(item_id),
    })


def decode_keyset_cursor(
    cursor: str, expected_sort: str, expected_order: str,
) -> tuple[str, UUID]:
    """Decode and validate a keyset cursor.

    Returns (sort_value_str, tiebreaker_id).
    Raises ValueError on invalid or mismatched cursor.
    """
    data = decode_cursor(cursor)
    if data.get("s") != expected_sort:
        raise ValueError(
            f"Cursor sort mismatch: cursor has sort={data.get('s')!r}, "
            f"request has sort={expected_sort!r}"
        )
    if data.get("o") != expected_order:
        raise ValueError(
            f"Cursor order mismatch: cursor has order={data.get('o')!r}, "
            f"request has order={expected_order!r}"
        )
    try:
        cursor_id = UUID(data["id"])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Invalid cursor id: {exc}") from exc
    sort_value = data.get("v")
    if sort_value is None:
        raise ValueError("Cursor missing sort value")
    return sort_value, cursor_id


def decode_page_cursor(cursor: str) -> int:
    """Decode a Forgejo page-number cursor. Returns the page number."""
    data = decode_cursor(cursor)
    page = data.get("p")
    if not isinstance(page, int) or page < 1:
        raise ValueError(f"Invalid page cursor: {data}")
    return page


def encode_page_cursor(page: int) -> str:
    """Encode a Forgejo page number as an opaque cursor."""
    return encode_cursor({"p": page})


def decode_offset_cursor(cursor: str) -> int:
    """Decode a search offset cursor. Returns the offset."""
    data = decode_cursor(cursor)
    offset = data.get("offset")
    if not isinstance(offset, int) or offset < 0:
        raise ValueError(f"Invalid offset cursor: {data}")
    return offset


def encode_offset_cursor(offset: int) -> str:
    """Encode a search offset as an opaque cursor."""
    return encode_cursor({"offset": offset})
