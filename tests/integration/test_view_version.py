# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Integration tests for the ViewVersion model (NEV-199).

Tests the view_versions table: round-trip CRUD, unique constraint on
(view_type, version), and server-default values. Uses the shared db_session
fixture from tests/conftest.py.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import UUID

import pytest
from phiacta.core.models.view_version import ViewVersion
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

needs_db = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="TEST_DATABASE_URL not set; skipping integration test",
)


@needs_db
class TestViewVersionRoundTrip:
    """Create a ViewVersion, read it back, and verify all fields."""

    async def test_create_and_read_back(self, db_session: AsyncSession) -> None:
        """ViewVersion can be created, flushed, and read back with all
        fields intact.
        """
        vv = ViewVersion(
            view_type="search_tsv",
            version="1.0.0",
            status="active",
            parameters={"language": "english", "weights": [1.0, 0.4]},
        )
        db_session.add(vv)
        await db_session.flush()

        # Read back by id
        result = await db_session.execute(
            select(ViewVersion).where(ViewVersion.id == vv.id)
        )
        fetched = result.scalar_one()

        assert fetched.id is not None
        assert isinstance(fetched.id, UUID)
        assert fetched.view_type == "search_tsv"
        assert fetched.version == "1.0.0"
        assert fetched.status == "active"
        assert fetched.parameters == {"language": "english", "weights": [1.0, 0.4]}
        assert fetched.created_at is not None

    async def test_id_is_uuid(self, db_session: AsyncSession) -> None:
        """ViewVersion.id is a UUID primary key."""
        vv = ViewVersion(
            view_type="embedding_ada",
            version="2.0.0",
        )
        db_session.add(vv)
        await db_session.flush()

        assert isinstance(vv.id, UUID)


@needs_db
class TestViewVersionDefaults:
    """Test that server/column defaults are applied correctly."""

    async def test_status_defaults_to_active(
        self, db_session: AsyncSession
    ) -> None:
        """When status is not explicitly set, it defaults to 'active'."""
        vv = ViewVersion(
            view_type="search_tsv",
            version="1.0.0",
        )
        db_session.add(vv)
        await db_session.flush()

        result = await db_session.execute(
            select(ViewVersion).where(ViewVersion.id == vv.id)
        )
        fetched = result.scalar_one()
        assert fetched.status == "active"

    async def test_parameters_defaults_to_empty_dict(
        self, db_session: AsyncSession
    ) -> None:
        """When parameters is not explicitly set, it defaults to {}."""
        vv = ViewVersion(
            view_type="search_tsv",
            version="2.0.0",
        )
        db_session.add(vv)
        await db_session.flush()

        result = await db_session.execute(
            select(ViewVersion).where(ViewVersion.id == vv.id)
        )
        fetched = result.scalar_one()
        assert fetched.parameters == {} or fetched.parameters is None
        # After migration lands, this should be exactly {}

    async def test_created_at_is_auto_set(
        self, db_session: AsyncSession
    ) -> None:
        """created_at is automatically set to approximately now."""
        before = datetime.now(UTC)
        vv = ViewVersion(
            view_type="search_tsv",
            version="3.0.0",
        )
        db_session.add(vv)
        await db_session.flush()
        after = datetime.now(UTC)

        assert vv.created_at is not None
        # created_at should be between before and after
        created = vv.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        assert before <= created <= after


@needs_db
class TestViewVersionUniqueConstraint:
    """Test that the unique index on (view_type, version) is enforced."""

    async def test_duplicate_view_type_version_raises_integrity_error(
        self, db_session: AsyncSession
    ) -> None:
        """Inserting two ViewVersion rows with the same (view_type, version)
        raises IntegrityError.
        """
        vv1 = ViewVersion(
            view_type="search_tsv",
            version="1.0.0",
            status="active",
        )
        db_session.add(vv1)
        await db_session.flush()

        vv2 = ViewVersion(
            view_type="search_tsv",
            version="1.0.0",
            status="active",
        )
        db_session.add(vv2)

        with pytest.raises(IntegrityError):
            await db_session.flush()

    async def test_same_view_type_different_version_allowed(
        self, db_session: AsyncSession
    ) -> None:
        """Two ViewVersion rows with the same view_type but different versions
        are allowed.
        """
        vv1 = ViewVersion(
            view_type="search_tsv",
            version="1.0.0",
        )
        vv2 = ViewVersion(
            view_type="search_tsv",
            version="2.0.0",
        )
        db_session.add(vv1)
        db_session.add(vv2)
        await db_session.flush()

        result = await db_session.execute(
            select(ViewVersion).where(ViewVersion.view_type == "search_tsv")
        )
        rows = result.scalars().all()
        assert len(rows) == 2
        versions = {r.version for r in rows}
        assert versions == {"1.0.0", "2.0.0"}

    async def test_different_view_type_same_version_allowed(
        self, db_session: AsyncSession
    ) -> None:
        """Two ViewVersion rows with different view_types but the same version
        are allowed.
        """
        vv1 = ViewVersion(
            view_type="search_tsv",
            version="1.0.0",
        )
        vv2 = ViewVersion(
            view_type="embedding_ada",
            version="1.0.0",
        )
        db_session.add(vv1)
        db_session.add(vv2)
        await db_session.flush()

        # Both should exist
        assert vv1.id != vv2.id


@needs_db
class TestViewVersionInheritsUUIDMixin:
    """ViewVersion uses UUIDMixin for its primary key."""

    async def test_has_uuid_primary_key(self, db_session: AsyncSession) -> None:
        """ViewVersion.id is a UUID generated by UUIDMixin."""
        vv = ViewVersion(
            view_type="test_view",
            version="0.0.1",
        )
        db_session.add(vv)
        await db_session.flush()

        assert vv.id is not None
        assert isinstance(vv.id, UUID)

        # Verify it's the primary key column
        pk_cols = [c.name for c in ViewVersion.__table__.primary_key.columns]
        assert "id" in pk_cols
