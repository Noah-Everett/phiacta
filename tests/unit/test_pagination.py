# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for PHI-193: cursor pagination utilities.

Tests the cursor encode/decode functions and the CursorPage schema
in isolation. These test the core/pagination.py module directly.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ValidationError

from phiacta.core.pagination import CursorPage, decode_cursor, encode_cursor


# ===========================================================================
# encode_cursor / decode_cursor roundtrip
# ===========================================================================


class TestEncodeCursorDecodeCursorRoundtrip:
    """Encode then decode must produce the original values."""

    def test_roundtrip_simple_dict(self) -> None:
        """A simple dict survives encode/decode roundtrip."""
        original = {"s": "created_at", "o": "desc", "v": "2026-03-15T12:00:00", "id": str(uuid4())}
        cursor = encode_cursor(original)
        decoded = decode_cursor(cursor)
        assert decoded == original

    def test_roundtrip_page_encoded(self) -> None:
        """Page-encoded cursor (Forgejo) roundtrips correctly."""
        original = {"p": 2}
        cursor = encode_cursor(original)
        decoded = decode_cursor(cursor)
        assert decoded == original

    def test_roundtrip_offset_encoded(self) -> None:
        """Offset-encoded cursor (search) roundtrips correctly."""
        original = {"offset": 20}
        cursor = encode_cursor(original)
        decoded = decode_cursor(cursor)
        assert decoded == original

    def test_roundtrip_with_uuid_string(self) -> None:
        """UUID strings in cursor values survive roundtrip."""
        uid = str(uuid4())
        original = {"s": "created_at", "o": "asc", "v": "2026-01-01T00:00:00", "id": uid}
        cursor = encode_cursor(original)
        decoded = decode_cursor(cursor)
        assert decoded["id"] == uid

    def test_roundtrip_preserves_all_keys(self) -> None:
        """All keys in the original dict are preserved after roundtrip."""
        original = {"a": 1, "b": "hello", "c": True, "d": None}
        cursor = encode_cursor(original)
        decoded = decode_cursor(cursor)
        assert decoded == original

    def test_encode_returns_string(self) -> None:
        """encode_cursor returns a string."""
        result = encode_cursor({"key": "value"})
        assert isinstance(result, str)

    def test_encode_returns_base64url(self) -> None:
        """encode_cursor returns a base64url-encoded string that can be decoded."""
        cursor = encode_cursor({"key": "value"})
        # Should be decodable as base64url (with padding restoration)
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded)
        parsed = json.loads(raw)
        assert parsed == {"key": "value"}

    def test_different_inputs_produce_different_cursors(self) -> None:
        """Different input dicts produce different cursor strings."""
        c1 = encode_cursor({"p": 1})
        c2 = encode_cursor({"p": 2})
        assert c1 != c2


# ===========================================================================
# decode_cursor error handling
# ===========================================================================


class TestDecodeCursorErrors:
    """decode_cursor raises ValueError on invalid input."""

    def test_invalid_base64_raises_value_error(self) -> None:
        """Non-base64 input raises ValueError."""
        with pytest.raises(ValueError):
            decode_cursor("not-valid-base64!!!")

    def test_valid_base64_invalid_json_raises_value_error(self) -> None:
        """Valid base64 but non-JSON content raises ValueError."""
        cursor = base64.urlsafe_b64encode(b"not json").decode().rstrip("=")
        with pytest.raises(ValueError):
            decode_cursor(cursor)

    def test_valid_base64_valid_json_not_dict_raises_value_error(self) -> None:
        """Valid base64 + JSON but not a dict (e.g., a list) raises ValueError."""
        cursor = base64.urlsafe_b64encode(json.dumps([1, 2, 3]).encode()).decode().rstrip("=")
        with pytest.raises(ValueError):
            decode_cursor(cursor)

    def test_empty_string_raises_value_error(self) -> None:
        """Empty string raises ValueError."""
        with pytest.raises(ValueError):
            decode_cursor("")

    def test_none_like_string_raises_value_error(self) -> None:
        """A string 'null' encoded as base64 (produces None JSON) raises ValueError."""
        cursor = base64.urlsafe_b64encode(b"null").decode().rstrip("=")
        with pytest.raises(ValueError):
            decode_cursor(cursor)

    def test_valid_json_number_raises_value_error(self) -> None:
        """A JSON number (not a dict) raises ValueError."""
        cursor = base64.urlsafe_b64encode(b"42").decode().rstrip("=")
        with pytest.raises(ValueError):
            decode_cursor(cursor)

    def test_valid_json_string_raises_value_error(self) -> None:
        """A JSON string (not a dict) raises ValueError."""
        cursor = base64.urlsafe_b64encode(json.dumps("hello").encode()).decode().rstrip("=")
        with pytest.raises(ValueError):
            decode_cursor(cursor)


# ===========================================================================
# CursorPage schema
# ===========================================================================


class TestCursorPageSchema:
    """CursorPage Pydantic model validation and serialization."""

    def test_valid_cursor_page_with_items(self) -> None:
        """A CursorPage with items, limit, has_more, next_cursor is valid."""
        page = CursorPage[dict](
            items=[{"a": 1}, {"a": 2}],
            limit=50,
            has_more=True,
            next_cursor="abc123",
        )
        assert len(page.items) == 2
        assert page.limit == 50
        assert page.has_more is True
        assert page.next_cursor == "abc123"

    def test_valid_cursor_page_last_page(self) -> None:
        """Last page: has_more=false, next_cursor=None."""
        page = CursorPage[dict](
            items=[{"a": 1}],
            limit=50,
            has_more=False,
            next_cursor=None,
        )
        assert page.has_more is False
        assert page.next_cursor is None

    def test_valid_cursor_page_empty_items(self) -> None:
        """Empty items list with has_more=false, next_cursor=None."""
        page = CursorPage[dict](
            items=[],
            limit=50,
            has_more=False,
            next_cursor=None,
        )
        assert page.items == []
        assert page.has_more is False
        assert page.next_cursor is None

    def test_cursor_page_no_total_field(self) -> None:
        """CursorPage must NOT have a 'total' field."""
        page = CursorPage[dict](
            items=[], limit=50, has_more=False, next_cursor=None,
        )
        serialized = page.model_dump(mode="json")
        assert "total" not in serialized

    def test_cursor_page_no_offset_field(self) -> None:
        """CursorPage must NOT have an 'offset' field."""
        page = CursorPage[dict](
            items=[], limit=50, has_more=False, next_cursor=None,
        )
        serialized = page.model_dump(mode="json")
        assert "offset" not in serialized

    def test_cursor_page_serialization_fields(self) -> None:
        """Serialized CursorPage has exactly: items, limit, has_more, next_cursor."""
        page = CursorPage[dict](
            items=[{"x": 1}],
            limit=25,
            has_more=True,
            next_cursor="cursor_value",
        )
        serialized = page.model_dump(mode="json")
        expected_keys = {"items", "limit", "has_more", "next_cursor"}
        assert set(serialized.keys()) == expected_keys

    def test_cursor_page_requires_items(self) -> None:
        """Omitting 'items' raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            CursorPage[dict](limit=50, has_more=False, next_cursor=None)
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("items",) for e in errors)

    def test_cursor_page_requires_limit(self) -> None:
        """Omitting 'limit' raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            CursorPage[dict](items=[], has_more=False, next_cursor=None)
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("limit",) for e in errors)

    def test_cursor_page_requires_has_more(self) -> None:
        """Omitting 'has_more' raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            CursorPage[dict](items=[], limit=50, next_cursor=None)
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("has_more",) for e in errors)

    def test_cursor_page_generic_with_pydantic_model(self) -> None:
        """CursorPage works with a Pydantic BaseModel as type parameter."""

        class MyItem(BaseModel):
            name: str
            value: int

        page = CursorPage[MyItem](
            items=[MyItem(name="test", value=42)],
            limit=10,
            has_more=False,
            next_cursor=None,
        )
        assert len(page.items) == 1
        assert page.items[0].name == "test"
        assert page.items[0].value == 42

    def test_cursor_page_generic_with_uuid_type(self) -> None:
        """CursorPage works with UUID items."""
        uid = uuid4()
        page = CursorPage[UUID](
            items=[uid],
            limit=10,
            has_more=False,
            next_cursor=None,
        )
        assert page.items[0] == uid

    def test_cursor_page_serialization_with_nested_model(self) -> None:
        """Serialized CursorPage correctly serializes nested Pydantic models."""

        class Nested(BaseModel):
            id: UUID
            created_at: datetime

        uid = uuid4()
        now = datetime.now(UTC)
        page = CursorPage[Nested](
            items=[Nested(id=uid, created_at=now)],
            limit=10,
            has_more=True,
            next_cursor="next",
        )
        serialized = page.model_dump(mode="json")
        assert serialized["items"][0]["id"] == str(uid)
        assert serialized["has_more"] is True
        assert serialized["next_cursor"] == "next"

    def test_cursor_page_next_cursor_is_string_or_none(self) -> None:
        """next_cursor accepts string or None, not other types."""
        # Valid string
        page = CursorPage[dict](
            items=[], limit=50, has_more=False, next_cursor="abc",
        )
        assert page.next_cursor == "abc"

        # Valid None
        page = CursorPage[dict](
            items=[], limit=50, has_more=False, next_cursor=None,
        )
        assert page.next_cursor is None

    def test_cursor_page_limit_is_positive_int(self) -> None:
        """Limit should be a positive integer."""
        page = CursorPage[dict](
            items=[], limit=1, has_more=False, next_cursor=None,
        )
        assert page.limit == 1

    def test_cursor_page_items_preserves_order(self) -> None:
        """Items list preserves insertion order."""
        items = [{"i": i} for i in range(10)]
        page = CursorPage[dict](
            items=items, limit=50, has_more=False, next_cursor=None,
        )
        for i, item in enumerate(page.items):
            assert item["i"] == i


# ===========================================================================
# CursorPage vs old PaginatedResponse
# ===========================================================================


class TestCursorPageIsNotPaginatedResponse:
    """CursorPage is a new type, distinct from the old PaginatedResponse."""

    def test_cursor_page_has_no_total(self) -> None:
        """CursorPage model does not accept a 'total' field as constructor arg."""
        # This verifies CursorPage is NOT the old PaginatedResponse
        page = CursorPage[dict](
            items=[], limit=50, has_more=False, next_cursor=None,
        )
        assert not hasattr(page, "total") or "total" not in page.model_fields

    def test_cursor_page_has_no_offset(self) -> None:
        """CursorPage model does not accept an 'offset' field as constructor arg."""
        page = CursorPage[dict](
            items=[], limit=50, has_more=False, next_cursor=None,
        )
        assert not hasattr(page, "offset") or "offset" not in page.model_fields

    def test_cursor_page_has_has_more_as_regular_field(self) -> None:
        """has_more is a regular field (not computed from total/offset)."""
        # Create with has_more=True but empty items — this must work
        # (old PaginatedResponse computed has_more from total/offset)
        page = CursorPage[dict](
            items=[], limit=50, has_more=True, next_cursor="more",
        )
        assert page.has_more is True

    def test_cursor_page_fields_are_exactly_four(self) -> None:
        """CursorPage has exactly 4 fields: items, limit, has_more, next_cursor."""
        fields = set(CursorPage[dict].model_fields.keys())
        assert fields == {"items", "limit", "has_more", "next_cursor"}
