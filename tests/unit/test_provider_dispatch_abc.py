# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for EntryDataProvider ABC and provider required_on_create (PHI-107).

Tests the abstract base class contract and the concrete provider declarations.
These are pure in-memory tests with no I/O or database interaction.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from phiacta.core.compose import EntryDataProvider


# ---------------------------------------------------------------------------
# EntryDataProvider.required_on_create default
# ---------------------------------------------------------------------------


class TestEntryDataProviderRequiredOnCreate:
    """Tests that the EntryDataProvider ABC declares a required_on_create
    attribute that defaults to an empty frozenset."""

    def test_required_on_create_defaults_to_empty_frozenset(self) -> None:
        """The ABC's required_on_create attribute should default to
        frozenset() when not overridden by a subclass."""

        class MinimalProvider(EntryDataProvider):
            name = "minimal"
            fields = frozenset({"test_field"})

            async def get_one(self, entity_id: UUID, db):  # type: ignore[override]
                return None

            async def get_many(self, entity_ids: list[UUID], db):  # type: ignore[override]
                return {}

        provider = MinimalProvider()
        assert hasattr(provider, "required_on_create")
        assert provider.required_on_create == frozenset()
        assert isinstance(provider.required_on_create, frozenset)

    def test_required_on_create_is_frozenset_type(self) -> None:
        """The default required_on_create should be exactly a frozenset."""

        class CheckType(EntryDataProvider):
            name = "check"
            fields = frozenset({"x"})

            async def get_one(self, entity_id: UUID, db):  # type: ignore[override]
                return None

            async def get_many(self, entity_ids: list[UUID], db):  # type: ignore[override]
                return {}

        provider = CheckType()
        assert type(provider.required_on_create) is frozenset


# ---------------------------------------------------------------------------
# MetadataProvider.required_on_create declaration
# ---------------------------------------------------------------------------


class TestMetadataProviderRequiredOnCreate:
    """Tests that MetadataProvider correctly declares 'title' in
    required_on_create."""

    def test_required_on_create_is_frozenset_with_title(self) -> None:
        """MetadataProvider.required_on_create should be frozenset({'title'})."""
        from phiacta.extensions.metadata.provider import MetadataProvider

        provider = MetadataProvider()
        assert provider.required_on_create == frozenset({"title"})
        assert isinstance(provider.required_on_create, frozenset)

    def test_required_on_create_contains_only_title(self) -> None:
        """MetadataProvider.required_on_create should contain exactly
        one element: 'title'."""
        from phiacta.extensions.metadata.provider import MetadataProvider

        provider = MetadataProvider()
        assert len(provider.required_on_create) == 1
        assert "title" in provider.required_on_create

    def test_summary_is_not_required_on_create(self) -> None:
        """MetadataProvider should NOT require 'summary' on create."""
        from phiacta.extensions.metadata.provider import MetadataProvider

        provider = MetadataProvider()
        assert "summary" not in provider.required_on_create


# ---------------------------------------------------------------------------
# TypeProvider.required_on_create declaration
# ---------------------------------------------------------------------------


class TestTypeProviderRequiredOnCreate:
    """TypeProvider should have an empty required_on_create."""

    def test_required_on_create_is_empty(self) -> None:
        from phiacta.extensions.types.provider import TypeProvider

        provider = TypeProvider()
        assert provider.required_on_create == frozenset()

    def test_entry_type_is_not_required_on_create(self) -> None:
        from phiacta.extensions.types.provider import TypeProvider

        provider = TypeProvider()
        assert "entry_type" not in provider.required_on_create


# ---------------------------------------------------------------------------
# TagProvider.required_on_create declaration
# ---------------------------------------------------------------------------


class TestTagProviderRequiredOnCreate:
    """TagProvider should have an empty required_on_create."""

    def test_required_on_create_is_empty(self) -> None:
        from phiacta.extensions.tags.provider import TagProvider

        provider = TagProvider()
        assert provider.required_on_create == frozenset()


# ---------------------------------------------------------------------------
# EntryCreate schema changes
# ---------------------------------------------------------------------------


class TestEntryCreateSchema:
    """Tests that EntryCreate no longer has title, summary, entry_type as
    explicit fields -- they arrive via extra='allow'."""

    def test_entry_create_has_content_format_field(self) -> None:
        from phiacta.core.schemas.entry import EntryCreate

        assert "content_format" in EntryCreate.model_fields

    def test_entry_create_has_content_field(self) -> None:
        from phiacta.core.schemas.entry import EntryCreate

        assert "content" in EntryCreate.model_fields

    def test_entry_create_does_not_have_title_as_explicit_field(self) -> None:
        from phiacta.core.schemas.entry import EntryCreate

        assert "title" not in EntryCreate.model_fields

    def test_entry_create_does_not_have_summary_as_explicit_field(self) -> None:
        from phiacta.core.schemas.entry import EntryCreate

        assert "summary" not in EntryCreate.model_fields

    def test_entry_create_does_not_have_entry_type_as_explicit_field(self) -> None:
        from phiacta.core.schemas.entry import EntryCreate

        assert "entry_type" not in EntryCreate.model_fields

    def test_entry_create_allows_extra_fields(self) -> None:
        from phiacta.core.schemas.entry import EntryCreate

        body = EntryCreate.model_validate(
            {"content_format": "markdown", "title": "Test", "tags": ["a"]}
        )
        extras = body.model_extra or {}
        assert "title" in extras
        assert extras["title"] == "Test"
        assert "tags" in extras
        assert extras["tags"] == ["a"]
