# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for EntryDataProvider filter interface and provider implementations."""

from __future__ import annotations

import pytest

from phiacta.core.compose import EntryDataProvider


class TestEntryDataProviderDefaults:
    """Verify the base class defaults for the filter interface."""

    def test_filterable_fields_empty_by_default(self) -> None:
        assert EntryDataProvider.filterable_fields == frozenset()

    def test_apply_search_filter_raises_not_implemented(self) -> None:
        """A provider that declares filterable_fields but doesn't override
        apply_search_filter should raise NotImplementedError."""

        class StubProvider(EntryDataProvider):
            name = "stub"
            fields = frozenset({"x"})
            filterable_fields = frozenset({"x"})

            async def get_one(self, entity_id, db):
                return None

            async def get_many(self, entity_ids, db):
                return {}

        provider = StubProvider()
        with pytest.raises(NotImplementedError, match="stub"):
            provider.apply_search_filter(None, None, "x", "val")


class TestTypeProviderFilter:
    """Unit tests for TypeProvider.apply_search_filter."""

    def _make_provider(self):
        from phiacta.extensions.types.provider import TypeProvider
        return TypeProvider()

    def test_filterable_fields_declared(self) -> None:
        p = self._make_provider()
        assert "entry_type" in p.filterable_fields

    def test_empty_value_returns_stmt_unchanged(self) -> None:
        p = self._make_provider()
        sentinel = object()
        result = p.apply_search_filter(sentinel, None, "entry_type", "")
        assert result is sentinel

    def test_whitespace_only_value_returns_stmt_unchanged(self) -> None:
        p = self._make_provider()
        sentinel = object()
        result = p.apply_search_filter(sentinel, None, "entry_type", "  ,  , ")
        assert result is sentinel


class TestTagProviderFilter:
    """Unit tests for TagProvider.apply_search_filter."""

    def _make_provider(self):
        from phiacta.extensions.tags.provider import TagProvider
        return TagProvider()

    def test_filterable_fields_declared(self) -> None:
        p = self._make_provider()
        assert "tags" in p.filterable_fields

    def test_empty_value_returns_stmt_unchanged(self) -> None:
        p = self._make_provider()
        sentinel = object()
        result = p.apply_search_filter(sentinel, None, "tags", "")
        assert result is sentinel

    def test_whitespace_only_value_returns_stmt_unchanged(self) -> None:
        p = self._make_provider()
        sentinel = object()
        result = p.apply_search_filter(sentinel, None, "tags", "  ,  , ")
        assert result is sentinel

    def test_mode_defaults_to_or(self) -> None:
        """Without ;mode=, the default is OR (any tag matches)."""
        p = self._make_provider()
        # We can't easily inspect the SQL, but we can verify it doesn't crash
        # and returns something different from the input.
        from sqlalchemy import select, Column, Uuid
        from phiacta.core.models.entry import Entry
        stmt = select(Entry.id)
        result = p.apply_search_filter(stmt, Entry.id, "tags", "a,b")
        assert result is not stmt  # modified

    def test_mode_and_parsed_from_value(self) -> None:
        p = self._make_provider()
        from sqlalchemy import select
        from phiacta.core.models.entry import Entry
        stmt = select(Entry.id)
        result = p.apply_search_filter(stmt, Entry.id, "tags", "a,b;mode=and")
        assert result is not stmt

    def test_invalid_mode_ignored(self) -> None:
        """An invalid mode string falls through to default OR behavior."""
        p = self._make_provider()
        from sqlalchemy import select
        from phiacta.core.models.entry import Entry
        stmt = select(Entry.id)
        result = p.apply_search_filter(stmt, Entry.id, "tags", "a,b;mode=xor")
        assert result is not stmt  # still modifies (defaults to OR)
