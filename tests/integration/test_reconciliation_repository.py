# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Integration tests for EntryRepository.list_all_for_reconciliation() (NEV-164).

Tests the new repository method that returns all Entry ORM objects
for use by the reconciliation service. Uses a real test database.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.user import User
from phiacta.core.models.entry import Entry
from phiacta.core.repositories.entry_repository import EntryRepository
from tests.conftest import make_user, make_entry

needs_db = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="TEST_DATABASE_URL not set; skipping integration test",
)


@needs_db
class TestListAllForReconciliation:
    """Tests for EntryRepository.list_all_for_reconciliation()."""

    async def test_returns_all_entries(self, db_session: AsyncSession) -> None:
        """Should return all entries regardless of status."""
        user = User(**make_user())
        db_session.add(user)
        await db_session.flush()

        repo = EntryRepository(db_session)

        active = Entry(**make_entry(created_by=user.id, title="Active", status="active"))
        archived = Entry(**make_entry(created_by=user.id, title="Archived", status="archived"))
        draft = Entry(**make_entry(created_by=user.id, title="Draft", status="draft"))

        for entry in [active, archived, draft]:
            await repo.create(entry)

        results = await repo.list_all_for_reconciliation()

        assert len(results) >= 3
        result_ids = {r.id for r in results}
        assert active.id in result_ids
        assert archived.id in result_ids
        assert draft.id in result_ids

    async def test_returns_empty_for_empty_db(self, db_session: AsyncSession) -> None:
        """Empty database should return empty list."""
        repo = EntryRepository(db_session)
        results = await repo.list_all_for_reconciliation()
        assert results == []

    async def test_includes_required_fields(self, db_session: AsyncSession) -> None:
        """Each result must include: id, current_head_sha, repo_status, status."""
        user = User(**make_user())
        db_session.add(user)
        await db_session.flush()

        repo = EntryRepository(db_session)
        entry = Entry(**make_entry(created_by=user.id, title="Fields Test"))
        entry.current_head_sha = "a" * 40
        entry.repo_status = "ready"
        await repo.create(entry)

        results = await repo.list_all_for_reconciliation()
        assert len(results) >= 1

        our_result = next(r for r in results if r.id == entry.id)
        assert our_result.id == entry.id
        assert our_result.current_head_sha == "a" * 40
        assert our_result.repo_status == "ready"
        assert our_result.status == "active"

    async def test_entries_with_null_head_sha_included(
        self, db_session: AsyncSession
    ) -> None:
        """Entries with current_head_sha=None should still be returned."""
        user = User(**make_user())
        db_session.add(user)
        await db_session.flush()

        repo = EntryRepository(db_session)
        entry = Entry(**make_entry(created_by=user.id, title="No SHA"))
        assert entry.current_head_sha is None
        await repo.create(entry)

        results = await repo.list_all_for_reconciliation()
        result_ids = {r.id for r in results}
        assert entry.id in result_ids

    async def test_many_entries_all_returned(self, db_session: AsyncSession) -> None:
        """Should handle a realistic number of entries without pagination issues."""
        user = User(**make_user())
        db_session.add(user)
        await db_session.flush()

        repo = EntryRepository(db_session)
        created_ids = set()
        for i in range(25):
            entry = Entry(**make_entry(created_by=user.id, title=f"Entry {i}"))
            await repo.create(entry)
            created_ids.add(entry.id)

        results = await repo.list_all_for_reconciliation()
        result_ids = {r.id for r in results}
        assert created_ids.issubset(result_ids)

    async def test_provisioning_entries_included(
        self, db_session: AsyncSession
    ) -> None:
        """Provisioning entries must be included for stuck-provisioning detection."""
        user = User(**make_user())
        db_session.add(user)
        await db_session.flush()

        repo = EntryRepository(db_session)
        entry = Entry(**make_entry(created_by=user.id, title="Provisioning"))
        assert entry.repo_status == "provisioning"
        await repo.create(entry)

        results = await repo.list_all_for_reconciliation()
        result_ids = {r.id for r in results}
        assert entry.id in result_ids
