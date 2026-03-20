# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for search_tsv compute logic (NEV-130).

Tests the compute_search_tsv function with mocked repository calls.
Verifies branching logic: null/empty content -> delete, valid content -> upsert,
no active version -> no-op.

No database or HTTP — all DB interactions are mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# compute_search_tsv branching logic
# ---------------------------------------------------------------------------


class TestComputeSearchTsvBranching:
    """Tests for compute_search_tsv() logic branches.

    These tests mock the repository to verify that compute_search_tsv
    calls the right repository methods based on input conditions.
    """

    async def test_valid_content_calls_upsert(self) -> None:
        """compute_search_tsv with valid content calls repository.upsert()."""
        from phiacta.views.search_tsv.compute import compute_search_tsv

        entry_id = uuid4()
        version_id = uuid4()
        db = AsyncMock()
        content = "Valid content for tsvector computation."

        with (
            patch(
                "phiacta.views.search_tsv.compute.upsert", new_callable=AsyncMock
            ) as mock_upsert,
            patch(
                "phiacta.views.search_tsv.compute.delete_by_entry",
                new_callable=AsyncMock,
            ) as mock_delete,
        ):
            await compute_search_tsv(
                entry_id=entry_id,
                content_cache=content,
                version_id=version_id,
                db=db,
            )
            mock_upsert.assert_called_once()
            call_kwargs = mock_upsert.call_args
            # Verify entry_id and version_id are passed correctly
            assert call_kwargs.kwargs.get("entry_id") == entry_id or (
                call_kwargs.args and call_kwargs.args[0] == entry_id
            )
            mock_delete.assert_not_called()

    async def test_none_content_calls_delete(self) -> None:
        """compute_search_tsv with content_cache=None calls repository.delete_by_entry()."""
        from phiacta.views.search_tsv.compute import compute_search_tsv

        entry_id = uuid4()
        version_id = uuid4()
        db = AsyncMock()

        with (
            patch(
                "phiacta.views.search_tsv.compute.upsert", new_callable=AsyncMock
            ) as mock_upsert,
            patch(
                "phiacta.views.search_tsv.compute.delete_by_entry",
                new_callable=AsyncMock,
            ) as mock_delete,
        ):
            await compute_search_tsv(
                entry_id=entry_id,
                content_cache=None,
                version_id=version_id,
                db=db,
            )
            mock_delete.assert_called_once()
            mock_upsert.assert_not_called()

    async def test_empty_string_content_calls_delete(self) -> None:
        """compute_search_tsv with content_cache="" calls repository.delete_by_entry().

        Critical scenario #10: empty string treated same as None.
        """
        from phiacta.views.search_tsv.compute import compute_search_tsv

        entry_id = uuid4()
        version_id = uuid4()
        db = AsyncMock()

        with (
            patch(
                "phiacta.views.search_tsv.compute.upsert", new_callable=AsyncMock
            ) as mock_upsert,
            patch(
                "phiacta.views.search_tsv.compute.delete_by_entry",
                new_callable=AsyncMock,
            ) as mock_delete,
        ):
            await compute_search_tsv(
                entry_id=entry_id,
                content_cache="",
                version_id=version_id,
                db=db,
            )
            mock_delete.assert_called_once()
            mock_upsert.assert_not_called()

    async def test_whitespace_only_content_calls_delete(self) -> None:
        """compute_search_tsv with whitespace-only content calls delete.

        Whitespace-only content has no searchable tokens — treat as empty.
        """
        from phiacta.views.search_tsv.compute import compute_search_tsv

        entry_id = uuid4()
        version_id = uuid4()
        db = AsyncMock()

        with (
            patch(
                "phiacta.views.search_tsv.compute.upsert", new_callable=AsyncMock
            ) as mock_upsert,
            patch(
                "phiacta.views.search_tsv.compute.delete_by_entry",
                new_callable=AsyncMock,
            ) as mock_delete,
        ):
            await compute_search_tsv(
                entry_id=entry_id,
                content_cache="   \t\n  ",
                version_id=version_id,
                db=db,
            )
            mock_delete.assert_called_once()
            mock_upsert.assert_not_called()

    async def test_none_version_id_looks_up_active_version(self) -> None:
        """compute_search_tsv with version_id=None looks up the active version.

        Critical scenario #8 path: when no version_id is explicitly passed,
        the function should query for the active version.
        """
        from phiacta.views.search_tsv.compute import compute_search_tsv

        entry_id = uuid4()
        active_version_id = uuid4()
        db = AsyncMock()

        mock_version = MagicMock()
        mock_version.id = active_version_id

        with (
            patch(
                "phiacta.views.search_tsv.compute.get_active_version",
                new_callable=AsyncMock,
                return_value=mock_version,
            ) as mock_get_version,
            patch(
                "phiacta.views.search_tsv.compute.upsert", new_callable=AsyncMock
            ) as mock_upsert,
            patch(
                "phiacta.views.search_tsv.compute.delete_by_entry",
                new_callable=AsyncMock,
            ),
        ):
            await compute_search_tsv(
                entry_id=entry_id,
                content_cache="Content with version lookup.",
                version_id=None,
                db=db,
            )
            mock_get_version.assert_called_once()
            mock_upsert.assert_called_once()

    async def test_no_active_version_is_noop(self) -> None:
        """compute_search_tsv with no active version does not upsert or delete.

        Critical scenario #8: no active ViewVersion -> log warning, no-op.
        """
        from phiacta.views.search_tsv.compute import compute_search_tsv

        entry_id = uuid4()
        db = AsyncMock()

        with (
            patch(
                "phiacta.views.search_tsv.compute.get_active_version",
                new_callable=AsyncMock,
                return_value=None,
            ) as mock_get_version,
            patch(
                "phiacta.views.search_tsv.compute.upsert", new_callable=AsyncMock
            ) as mock_upsert,
            patch(
                "phiacta.views.search_tsv.compute.delete_by_entry",
                new_callable=AsyncMock,
            ) as mock_delete,
        ):
            await compute_search_tsv(
                entry_id=entry_id,
                content_cache="Content that will not be computed.",
                version_id=None,
                db=db,
            )
            mock_get_version.assert_called_once()
            mock_upsert.assert_not_called()
            mock_delete.assert_not_called()


# ---------------------------------------------------------------------------
# compute_search_tsv argument passing
# ---------------------------------------------------------------------------


class TestComputeSearchTsvArguments:
    """Tests that compute_search_tsv passes correct arguments to repository."""

    async def test_upsert_receives_correct_entry_id(self) -> None:
        """repository.upsert() receives the exact entry_id passed to compute."""
        from phiacta.views.search_tsv.compute import compute_search_tsv

        entry_id = uuid4()
        version_id = uuid4()
        db = AsyncMock()

        with (
            patch(
                "phiacta.views.search_tsv.compute.upsert", new_callable=AsyncMock
            ) as mock_upsert,
            patch(
                "phiacta.views.search_tsv.compute.delete_by_entry",
                new_callable=AsyncMock,
            ),
        ):
            await compute_search_tsv(
                entry_id=entry_id,
                content_cache="Test content.",
                version_id=version_id,
                db=db,
            )
            # Verify entry_id was passed
            call_kwargs = mock_upsert.call_args.kwargs
            assert call_kwargs["entry_id"] == entry_id

    async def test_upsert_receives_correct_version_id(self) -> None:
        """repository.upsert() receives the exact version_id passed to compute."""
        from phiacta.views.search_tsv.compute import compute_search_tsv

        entry_id = uuid4()
        version_id = uuid4()
        db = AsyncMock()

        with (
            patch(
                "phiacta.views.search_tsv.compute.upsert", new_callable=AsyncMock
            ) as mock_upsert,
            patch(
                "phiacta.views.search_tsv.compute.delete_by_entry",
                new_callable=AsyncMock,
            ),
        ):
            await compute_search_tsv(
                entry_id=entry_id,
                content_cache="Test content.",
                version_id=version_id,
                db=db,
            )
            call_kwargs = mock_upsert.call_args.kwargs
            assert call_kwargs["version_id"] == version_id

    async def test_upsert_receives_content_string(self) -> None:
        """repository.upsert() receives the content string for to_tsvector."""
        from phiacta.views.search_tsv.compute import compute_search_tsv

        entry_id = uuid4()
        version_id = uuid4()
        db = AsyncMock()
        content = "Specific content to be vectorized."

        with (
            patch(
                "phiacta.views.search_tsv.compute.upsert", new_callable=AsyncMock
            ) as mock_upsert,
            patch(
                "phiacta.views.search_tsv.compute.delete_by_entry",
                new_callable=AsyncMock,
            ),
        ):
            await compute_search_tsv(
                entry_id=entry_id,
                content_cache=content,
                version_id=version_id,
                db=db,
            )
            call_kwargs = mock_upsert.call_args.kwargs
            assert call_kwargs["content"] == content

    async def test_upsert_receives_db_session(self) -> None:
        """repository.upsert() receives the db session."""
        from phiacta.views.search_tsv.compute import compute_search_tsv

        entry_id = uuid4()
        version_id = uuid4()
        db = AsyncMock()

        with (
            patch(
                "phiacta.views.search_tsv.compute.upsert", new_callable=AsyncMock
            ) as mock_upsert,
            patch(
                "phiacta.views.search_tsv.compute.delete_by_entry",
                new_callable=AsyncMock,
            ),
        ):
            await compute_search_tsv(
                entry_id=entry_id,
                content_cache="Test.",
                version_id=version_id,
                db=db,
            )
            call_kwargs = mock_upsert.call_args.kwargs
            assert call_kwargs["db"] is db

    async def test_delete_receives_correct_entry_and_version(self) -> None:
        """repository.delete_by_entry() receives correct entry_id and version_id."""
        from phiacta.views.search_tsv.compute import compute_search_tsv

        entry_id = uuid4()
        version_id = uuid4()
        db = AsyncMock()

        with (
            patch(
                "phiacta.views.search_tsv.compute.upsert", new_callable=AsyncMock
            ),
            patch(
                "phiacta.views.search_tsv.compute.delete_by_entry",
                new_callable=AsyncMock,
            ) as mock_delete,
        ):
            await compute_search_tsv(
                entry_id=entry_id,
                content_cache=None,
                version_id=version_id,
                db=db,
            )
            call_kwargs = mock_delete.call_args.kwargs
            assert call_kwargs["entry_id"] == entry_id
            assert call_kwargs["version_id"] == version_id
            assert call_kwargs["db"] is db


# ---------------------------------------------------------------------------
# Plugin manifest
# ---------------------------------------------------------------------------


class TestSearchTsvManifest:
    """Tests for the search_tsv plugin manifest."""

    def test_manifest_exists_and_has_correct_name(self) -> None:
        """The search_tsv plugin exposes a manifest with name='search_tsv'."""
        from phiacta.views.search_tsv import manifest

        assert manifest.name == "search_tsv"

    def test_manifest_type_is_view(self) -> None:
        """The search_tsv manifest type is PluginType.VIEW."""
        from phiacta.plugin import PluginType
        from phiacta.views.search_tsv import manifest

        assert manifest.type == PluginType.VIEW

    def test_manifest_is_plugin_manifest_instance(self) -> None:
        """The manifest is a PluginManifest instance."""
        from phiacta.plugin import PluginManifest
        from phiacta.views.search_tsv import manifest

        assert isinstance(manifest, PluginManifest)
