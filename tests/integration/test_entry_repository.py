# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

import os
from uuid import uuid4

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
class TestCreateAndGetEntry:
    async def test_create_and_get_entry(self, db_session: AsyncSession) -> None:
        user = User(**make_user())
        db_session.add(user)
        await db_session.flush()

        repo = EntryRepository(db_session)
        entry_kwargs = make_entry(created_by=user.id)
        entry = Entry(**entry_kwargs)
        created = await repo.create(entry)

        assert created.id == entry.id
        assert created.repo_name is not None

        fetched = await repo.get_by_id(entry.id)
        assert fetched is not None
        assert fetched.id == entry.id

    async def test_get_nonexistent_returns_none(self, db_session: AsyncSession) -> None:
        repo = EntryRepository(db_session)
        result = await repo.get_by_id(uuid4())
        assert result is None


@needs_db
class TestListEntriesByVisibility:
    async def test_list_entries_by_visibility(self, db_session: AsyncSession) -> None:
        user = User(**make_user())
        db_session.add(user)
        await db_session.flush()

        repo = EntryRepository(db_session)
        entry = Entry(**make_entry(created_by=user.id, visibility="public"))
        await repo.create(entry)

        public = await repo.list_entries(visibility="public")
        assert any(e.id == entry.id for e in public)

        private = await repo.list_entries(visibility="private")
        assert all(e.id != entry.id for e in private)
