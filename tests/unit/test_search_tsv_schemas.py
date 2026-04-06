# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for search_tsv view schemas (NEV-130).

Tests pure validation and data transformation logic. No database or HTTP.
All tests should FAIL against the stubs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# SearchTsvResponse schema
# ---------------------------------------------------------------------------


class TestSearchTsvResponseSchema:
    """Tests for the SearchTsvResponse schema (Pydantic model for GET /{entry_id})."""

    def test_construction_with_all_fields(self) -> None:
        """SearchTsvResponse can be constructed with entry_id, version_id, tsv, computed_at."""
        from phiacta.extensions.search_tsv.schemas import SearchTsvResponse

        entry_id = uuid4()
        version_id = uuid4()
        now = datetime.now(tz=timezone.utc)

        resp = SearchTsvResponse(
            entry_id=entry_id,
            version_id=version_id,
            tsv="'entangl':3 'physic':5 'quantum':1",
            computed_at=now,
        )
        assert resp.entry_id == entry_id
        assert resp.version_id == version_id
        assert resp.tsv == "'entangl':3 'physic':5 'quantum':1"
        assert resp.computed_at == now

    def test_entry_id_is_uuid(self) -> None:
        """SearchTsvResponse.entry_id must be a UUID."""
        from phiacta.extensions.search_tsv.schemas import SearchTsvResponse

        entry_id = uuid4()
        version_id = uuid4()
        now = datetime.now(tz=timezone.utc)

        resp = SearchTsvResponse(
            entry_id=entry_id,
            version_id=version_id,
            tsv="'test':1",
            computed_at=now,
        )
        assert resp.entry_id == entry_id

    def test_version_id_is_uuid(self) -> None:
        """SearchTsvResponse.version_id must be a UUID."""
        from phiacta.extensions.search_tsv.schemas import SearchTsvResponse

        entry_id = uuid4()
        version_id = uuid4()
        now = datetime.now(tz=timezone.utc)

        resp = SearchTsvResponse(
            entry_id=entry_id,
            version_id=version_id,
            tsv="'test':1",
            computed_at=now,
        )
        assert resp.version_id == version_id

    def test_tsv_is_string(self) -> None:
        """SearchTsvResponse.tsv is a string representation of the tsvector."""
        from phiacta.extensions.search_tsv.schemas import SearchTsvResponse

        resp = SearchTsvResponse(
            entry_id=uuid4(),
            version_id=uuid4(),
            tsv="'complex':1 'tsvector':2 'represent':3",
            computed_at=datetime.now(tz=timezone.utc),
        )
        assert isinstance(resp.tsv, str)
        assert len(resp.tsv) > 0

    def test_computed_at_is_datetime(self) -> None:
        """SearchTsvResponse.computed_at is a datetime."""
        from phiacta.extensions.search_tsv.schemas import SearchTsvResponse

        now = datetime.now(tz=timezone.utc)
        resp = SearchTsvResponse(
            entry_id=uuid4(),
            version_id=uuid4(),
            tsv="'test':1",
            computed_at=now,
        )
        assert resp.computed_at == now

    def test_empty_tsv_string_is_valid(self) -> None:
        """SearchTsvResponse accepts an empty tsv string (edge case)."""
        from phiacta.extensions.search_tsv.schemas import SearchTsvResponse

        resp = SearchTsvResponse(
            entry_id=uuid4(),
            version_id=uuid4(),
            tsv="",
            computed_at=datetime.now(tz=timezone.utc),
        )
        assert resp.tsv == ""


# ---------------------------------------------------------------------------
# SearchTsvVersionResponse schema
# ---------------------------------------------------------------------------


class TestSearchTsvVersionResponseSchema:
    """Tests for the SearchTsvVersionResponse schema (Pydantic model for GET /version)."""

    def test_construction_with_all_fields(self) -> None:
        """SearchTsvVersionResponse can be constructed with all fields."""
        from phiacta.extensions.search_tsv.schemas import SearchTsvVersionResponse

        vid = uuid4()
        resp = SearchTsvVersionResponse(
            id=vid,
            view_type="search_tsv",
            version="v1",
            status="active",
            parameters={"language": "english"},
        )
        assert resp.id == vid
        assert resp.view_type == "search_tsv"
        assert resp.version == "v1"
        assert resp.status == "active"
        assert resp.parameters == {"language": "english"}

    def test_view_type_field(self) -> None:
        """SearchTsvVersionResponse.view_type is a string."""
        from phiacta.extensions.search_tsv.schemas import SearchTsvVersionResponse

        resp = SearchTsvVersionResponse(
            id=uuid4(),
            view_type="search_tsv",
            version="v2",
            status="active",
            parameters={},
        )
        assert resp.view_type == "search_tsv"

    def test_parameters_is_dict(self) -> None:
        """SearchTsvVersionResponse.parameters is a dict."""
        from phiacta.extensions.search_tsv.schemas import SearchTsvVersionResponse

        resp = SearchTsvVersionResponse(
            id=uuid4(),
            view_type="search_tsv",
            version="v1",
            status="active",
            parameters={"language": "english", "weights": [1.0, 0.4]},
        )
        assert isinstance(resp.parameters, dict)
        assert resp.parameters["language"] == "english"

    def test_empty_parameters_is_valid(self) -> None:
        """SearchTsvVersionResponse with empty parameters dict is valid."""
        from phiacta.extensions.search_tsv.schemas import SearchTsvVersionResponse

        resp = SearchTsvVersionResponse(
            id=uuid4(),
            view_type="search_tsv",
            version="v1",
            status="active",
            parameters={},
        )
        assert resp.parameters == {}

    def test_status_values(self) -> None:
        """SearchTsvVersionResponse accepts various status values as strings."""
        from phiacta.extensions.search_tsv.schemas import SearchTsvVersionResponse

        for status in ["active", "deprecated", "pending"]:
            resp = SearchTsvVersionResponse(
                id=uuid4(),
                view_type="search_tsv",
                version="v1",
                status=status,
                parameters={},
            )
            assert resp.status == status
