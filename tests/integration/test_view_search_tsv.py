# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Integration tests for the search_tsv view model and repository (NEV-130).

Tests the view_search_tsv table: round-trip CRUD, composite primary key,
ON DELETE CASCADE, GIN index presence, and repository operations.

Requires PostgreSQL for TSVECTOR column type and to_tsvector function.
Uses the shared db_session fixture from tests/conftest.py.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.agent import Agent
from phiacta.core.models.entry import Entry
from phiacta.core.models.view_version import ViewVersion
from phiacta.views.search_tsv.models import ViewSearchTsv  # noqa: F401 — register with Base before create_all

needs_pg = pytest.mark.skipif(
    "postgresql" not in os.environ.get("TEST_DATABASE_URL", ""),
    reason="search_tsv integration tests require PostgreSQL (TSVECTOR type)",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_agent(db: AsyncSession) -> Agent:
    """Create and flush a minimal Agent row."""
    agent = Agent(
        id=uuid4(),
        agent_type="human",
        handle=f"test-{uuid4().hex[:8]}",
        email=f"test-{uuid4().hex[:8]}@example.com",
        password_hash="$2b$12$fakehash",
    )
    db.add(agent)
    await db.flush()
    return agent


async def _create_entry(db: AsyncSession, agent_id: UUID) -> Entry:
    """Create and flush a minimal Entry row."""
    eid = uuid4()
    entry = Entry(
        id=eid,
        title="Integration Test Entry",
        content_format="markdown",
        repo_name=str(eid),
        created_by=agent_id,
        status="active",
        repo_status="ready",
    )
    db.add(entry)
    await db.flush()
    return entry


async def _create_version(
    db: AsyncSession,
    *,
    view_type: str = "search_tsv",
    version: str = "v1",
    status: str = "active",
) -> ViewVersion:
    """Create and flush a ViewVersion row."""
    vv = ViewVersion(
        view_type=view_type,
        version=version,
        status=status,
        parameters={"language": "english"},
    )
    db.add(vv)
    await db.flush()
    return vv


# ---------------------------------------------------------------------------
# Model round-trip tests
# ---------------------------------------------------------------------------


@needs_pg
class TestViewSearchTsvModel:
    """Test the ViewSearchTsv model: creation, reading, field types."""

    async def test_create_and_read_back(self, db_session: AsyncSession) -> None:
        """ViewSearchTsv can be created with entry_id, version_id and read back."""
        from phiacta.views.search_tsv.models import ViewSearchTsv

        agent = await _create_agent(db_session)
        entry = await _create_entry(db_session, agent.id)
        version = await _create_version(db_session)

        # Insert via raw SQL since tsvector column needs to_tsvector
        await db_session.execute(
            text(
                "INSERT INTO view_search_tsv (entry_id, version_id, tsv) "
                "VALUES (:eid, :vid, to_tsvector('english', :content))"
            ),
            {
                "eid": str(entry.id),
                "vid": str(version.id),
                "content": "Quantum mechanics is a fundamental theory in physics.",
            },
        )
        await db_session.flush()

        # Read back via ORM
        result = await db_session.execute(
            select(ViewSearchTsv).where(
                ViewSearchTsv.entry_id == entry.id,
                ViewSearchTsv.version_id == version.id,
            )
        )
        row = result.scalar_one()

        assert row.entry_id == entry.id
        assert row.version_id == version.id
        assert row.tsv is not None
        assert row.computed_at is not None
        assert isinstance(row.computed_at, datetime)

    async def test_composite_primary_key(self, db_session: AsyncSession) -> None:
        """ViewSearchTsv has a composite PK of (entry_id, version_id)."""
        from phiacta.views.search_tsv.models import ViewSearchTsv

        pk_cols = [
            c.name for c in ViewSearchTsv.__table__.primary_key.columns
        ]
        assert "entry_id" in pk_cols
        assert "version_id" in pk_cols
        assert len(pk_cols) == 2

    async def test_duplicate_entry_version_raises_integrity_error(
        self, db_session: AsyncSession
    ) -> None:
        """Inserting two rows with the same (entry_id, version_id) raises IntegrityError."""
        agent = await _create_agent(db_session)
        entry = await _create_entry(db_session, agent.id)
        version = await _create_version(db_session)

        await db_session.execute(
            text(
                "INSERT INTO view_search_tsv (entry_id, version_id, tsv) "
                "VALUES (:eid, :vid, to_tsvector('english', :content))"
            ),
            {
                "eid": str(entry.id),
                "vid": str(version.id),
                "content": "First insert.",
            },
        )
        await db_session.flush()

        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(
                    "INSERT INTO view_search_tsv (entry_id, version_id, tsv) "
                    "VALUES (:eid, :vid, to_tsvector('english', :content))"
                ),
                {
                    "eid": str(entry.id),
                    "vid": str(version.id),
                    "content": "Second insert — should fail.",
                },
            )
            await db_session.flush()

    async def test_same_entry_different_versions_allowed(
        self, db_session: AsyncSession
    ) -> None:
        """Same entry with different version_ids produces two rows."""
        agent = await _create_agent(db_session)
        entry = await _create_entry(db_session, agent.id)
        v1 = await _create_version(db_session, version="v1")
        v2 = await _create_version(db_session, version="v2", status="pending")

        for v in [v1, v2]:
            await db_session.execute(
                text(
                    "INSERT INTO view_search_tsv (entry_id, version_id, tsv) "
                    "VALUES (:eid, :vid, to_tsvector('english', :content))"
                ),
                {
                    "eid": str(entry.id),
                    "vid": str(v.id),
                    "content": f"Content for version {v.version}.",
                },
            )
        await db_session.flush()

        result = await db_session.execute(
            text(
                "SELECT count(*) FROM view_search_tsv WHERE entry_id = :eid"
            ),
            {"eid": str(entry.id)},
        )
        assert result.scalar_one() == 2


# ---------------------------------------------------------------------------
# FK constraint: entries(id) ON DELETE CASCADE
# ---------------------------------------------------------------------------


@needs_pg
class TestCascadeConstraint:
    """Test that ON DELETE CASCADE works on the entry_id FK."""

    async def test_entry_delete_cascades_to_view_search_tsv(
        self, db_session: AsyncSession
    ) -> None:
        """Deleting an entry row cascades to remove its view_search_tsv rows."""
        from phiacta.views.search_tsv.models import ViewSearchTsv  # noqa: F401

        agent = await _create_agent(db_session)
        entry = await _create_entry(db_session, agent.id)
        version = await _create_version(db_session)

        await db_session.execute(
            text(
                "INSERT INTO view_search_tsv (entry_id, version_id, tsv) "
                "VALUES (:eid, :vid, to_tsvector('english', :content))"
            ),
            {
                "eid": str(entry.id),
                "vid": str(version.id),
                "content": "Content to be cascaded.",
            },
        )
        await db_session.flush()

        # Delete the entry
        await db_session.execute(
            text("DELETE FROM entries WHERE id = :eid"),
            {"eid": str(entry.id)},
        )
        await db_session.flush()

        # view_search_tsv row should be gone
        result = await db_session.execute(
            text(
                "SELECT count(*) FROM view_search_tsv WHERE entry_id = :eid"
            ),
            {"eid": str(entry.id)},
        )
        assert result.scalar_one() == 0


# ---------------------------------------------------------------------------
# FK constraint: view_versions(id)
# ---------------------------------------------------------------------------


@needs_pg
class TestVersionFKConstraint:
    """Test that the version_id FK references view_versions."""

    async def test_invalid_version_id_raises_integrity_error(
        self, db_session: AsyncSession
    ) -> None:
        """Inserting with a non-existent version_id raises IntegrityError."""
        agent = await _create_agent(db_session)
        entry = await _create_entry(db_session, agent.id)
        fake_version_id = uuid4()

        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(
                    "INSERT INTO view_search_tsv (entry_id, version_id, tsv) "
                    "VALUES (:eid, :vid, to_tsvector('english', :content))"
                ),
                {
                    "eid": str(entry.id),
                    "vid": str(fake_version_id),
                    "content": "Should fail on FK.",
                },
            )
            await db_session.flush()


# ---------------------------------------------------------------------------
# GIN index verification
# ---------------------------------------------------------------------------


@needs_pg
class TestGINIndex:
    """Verify the GIN index on the tsv column exists."""

    async def test_gin_index_exists(self, db_session: AsyncSession) -> None:
        """The ix_view_search_tsv_gin index should exist in the database."""
        result = await db_session.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'view_search_tsv' "
                "AND indexname = 'ix_view_search_tsv_gin'"
            )
        )
        row = result.scalar_one_or_none()
        assert row is not None, "GIN index ix_view_search_tsv_gin not found"


# ---------------------------------------------------------------------------
# Repository tests
# ---------------------------------------------------------------------------


@needs_pg
class TestSearchTsvRepository:
    """Integration tests for the search_tsv repository functions."""

    async def test_upsert_creates_new_row(self, db_session: AsyncSession) -> None:
        """repository.upsert() creates a new row when none exists."""
        from phiacta.views.search_tsv.repository import upsert

        agent = await _create_agent(db_session)
        entry = await _create_entry(db_session, agent.id)
        version = await _create_version(db_session)

        await upsert(
            entry_id=entry.id,
            version_id=version.id,
            content="Upsert creates a new row for search.",
            db=db_session,
        )
        await db_session.flush()

        result = await db_session.execute(
            text(
                "SELECT count(*) FROM view_search_tsv "
                "WHERE entry_id = :eid AND version_id = :vid"
            ),
            {"eid": str(entry.id), "vid": str(version.id)},
        )
        assert result.scalar_one() == 1

    async def test_upsert_updates_existing_row(
        self, db_session: AsyncSession
    ) -> None:
        """repository.upsert() updates the tsvector when the row already exists."""
        from phiacta.views.search_tsv.repository import upsert, get_by_entry

        agent = await _create_agent(db_session)
        entry = await _create_entry(db_session, agent.id)
        version = await _create_version(db_session)

        # First upsert
        await upsert(
            entry_id=entry.id,
            version_id=version.id,
            content="First version of content.",
            db=db_session,
        )
        await db_session.flush()

        # Second upsert with different content
        await upsert(
            entry_id=entry.id,
            version_id=version.id,
            content="Completely different quantum physics content.",
            db=db_session,
        )
        await db_session.flush()

        # Still exactly one row
        result = await db_session.execute(
            text(
                "SELECT count(*) FROM view_search_tsv "
                "WHERE entry_id = :eid AND version_id = :vid"
            ),
            {"eid": str(entry.id), "vid": str(version.id)},
        )
        assert result.scalar_one() == 1

    async def test_get_by_entry_returns_row(
        self, db_session: AsyncSession
    ) -> None:
        """repository.get_by_entry() returns the row for a given entry+version."""
        from phiacta.views.search_tsv.repository import upsert, get_by_entry

        agent = await _create_agent(db_session)
        entry = await _create_entry(db_session, agent.id)
        version = await _create_version(db_session)

        await upsert(
            entry_id=entry.id,
            version_id=version.id,
            content="Retrievable content for testing.",
            db=db_session,
        )
        await db_session.flush()

        row = await get_by_entry(
            entry_id=entry.id, version_id=version.id, db=db_session
        )
        assert row is not None
        assert row.entry_id == entry.id
        assert row.version_id == version.id

    async def test_get_by_entry_returns_none_when_missing(
        self, db_session: AsyncSession
    ) -> None:
        """repository.get_by_entry() returns None when no row exists."""
        from phiacta.views.search_tsv.repository import get_by_entry

        version = await _create_version(db_session)

        row = await get_by_entry(
            entry_id=uuid4(), version_id=version.id, db=db_session
        )
        assert row is None

    async def test_delete_by_entry_removes_row(
        self, db_session: AsyncSession
    ) -> None:
        """repository.delete_by_entry() removes the row for a given entry+version."""
        from phiacta.views.search_tsv.repository import (
            upsert,
            delete_by_entry,
            get_by_entry,
        )

        agent = await _create_agent(db_session)
        entry = await _create_entry(db_session, agent.id)
        version = await _create_version(db_session)

        await upsert(
            entry_id=entry.id,
            version_id=version.id,
            content="Content to be deleted.",
            db=db_session,
        )
        await db_session.flush()

        await delete_by_entry(
            entry_id=entry.id, version_id=version.id, db=db_session
        )
        await db_session.flush()

        row = await get_by_entry(
            entry_id=entry.id, version_id=version.id, db=db_session
        )
        assert row is None

    async def test_delete_by_entry_noop_when_missing(
        self, db_session: AsyncSession
    ) -> None:
        """repository.delete_by_entry() is a no-op when no row exists."""
        from phiacta.views.search_tsv.repository import delete_by_entry

        version = await _create_version(db_session)

        # Should not raise
        await delete_by_entry(
            entry_id=uuid4(), version_id=version.id, db=db_session
        )

    async def test_get_active_version_returns_active(
        self, db_session: AsyncSession
    ) -> None:
        """repository.get_active_version() returns the active version for search_tsv."""
        from phiacta.views.search_tsv.repository import get_active_version

        version = await _create_version(db_session, status="active")

        result = await get_active_version(db=db_session)
        assert result is not None
        assert result.id == version.id
        assert result.view_type == "search_tsv"
        assert result.status == "active"

    async def test_get_active_version_returns_none_when_no_active(
        self, db_session: AsyncSession
    ) -> None:
        """repository.get_active_version() returns None when no active version."""
        from phiacta.views.search_tsv.repository import get_active_version

        # Create a non-active version
        await _create_version(db_session, status="deprecated")

        result = await get_active_version(db=db_session)
        assert result is None

    async def test_get_active_version_ignores_other_view_types(
        self, db_session: AsyncSession
    ) -> None:
        """repository.get_active_version() only returns search_tsv versions."""
        from phiacta.views.search_tsv.repository import get_active_version

        # Create an active version for a different view type
        vv = ViewVersion(
            view_type="embedding_ada",
            version="v1",
            status="active",
            parameters={},
        )
        db_session.add(vv)
        await db_session.flush()

        result = await get_active_version(db=db_session)
        assert result is None


# ---------------------------------------------------------------------------
# Computed_at timestamp
# ---------------------------------------------------------------------------


@needs_pg
class TestComputedAtTimestamp:
    """Verify computed_at is set correctly on upsert."""

    async def test_computed_at_set_on_insert(
        self, db_session: AsyncSession
    ) -> None:
        """computed_at is automatically set to approximately now on insert."""
        from phiacta.views.search_tsv.repository import upsert, get_by_entry

        agent = await _create_agent(db_session)
        entry = await _create_entry(db_session, agent.id)
        version = await _create_version(db_session)

        before = datetime.now(UTC)
        await upsert(
            entry_id=entry.id,
            version_id=version.id,
            content="Timestamp test content.",
            db=db_session,
        )
        await db_session.flush()
        after = datetime.now(UTC)

        row = await get_by_entry(
            entry_id=entry.id, version_id=version.id, db=db_session
        )
        assert row is not None
        computed = row.computed_at
        if computed.tzinfo is None:
            computed = computed.replace(tzinfo=UTC)
        # Allow 2-second tolerance for server-side now() vs Python-side datetime
        from datetime import timedelta
        assert before - timedelta(seconds=2) <= computed <= after + timedelta(seconds=2)
