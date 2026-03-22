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
        assert created.title == "Test Entry"

        fetched = await repo.get_by_id(entry.id)
        assert fetched is not None
        assert fetched.id == entry.id
        assert fetched.content_format == "markdown"

    async def test_get_nonexistent_returns_none(self, db_session: AsyncSession) -> None:
        repo = EntryRepository(db_session)
        result = await repo.get_by_id(uuid4())
        assert result is None


@needs_db
class TestListEntriesWithFilters:
    async def test_list_entries_with_layout_hint(self, db_session: AsyncSession) -> None:
        user = User(**make_user())
        db_session.add(user)
        await db_session.flush()

        repo = EntryRepository(db_session)

        paper = Entry(
            **make_entry(
                created_by=user.id,
                title="A Paper",
                layout_hint="paper",
            )
        )
        theorem = Entry(
            **make_entry(
                created_by=user.id,
                title="A Theorem",
                layout_hint="theorem",
            )
        )
        await repo.create(paper)
        await repo.create(theorem)

        papers = await repo.list_entries(layout_hint="paper")
        assert len(papers) >= 1
        assert all(e.layout_hint == "paper" for e in papers)

        theorems = await repo.list_entries(layout_hint="theorem")
        assert len(theorems) >= 1
        assert all(e.layout_hint == "theorem" for e in theorems)

    async def test_list_entries_by_status(self, db_session: AsyncSession) -> None:
        user = User(**make_user())
        db_session.add(user)
        await db_session.flush()

        repo = EntryRepository(db_session)
        entry = Entry(
            **make_entry(created_by=user.id, status="active")
        )
        await repo.create(entry)

        active = await repo.list_entries(status="active")
        assert len(active) >= 1
        assert all(e.status == "active" for e in active)

        archived = await repo.list_entries(status="archived")
        assert all(e.status == "archived" for e in archived)

    async def test_list_entries_pagination(self, db_session: AsyncSession) -> None:
        user = User(**make_user())
        db_session.add(user)
        await db_session.flush()

        repo = EntryRepository(db_session)

        for i in range(5):
            entry = Entry(
                **make_entry(
                    created_by=user.id,
                    title=f"Entry {i}",
                )
            )
            await repo.create(entry)

        page1 = await repo.list_entries(limit=2, offset=0)
        page2 = await repo.list_entries(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0].id != page2[0].id


@needs_db
class TestUpdateRepoStatus:
    async def test_update_repo_status(self, db_session: AsyncSession) -> None:
        user = User(**make_user())
        db_session.add(user)
        await db_session.flush()

        repo = EntryRepository(db_session)
        entry = Entry(**make_entry(created_by=user.id))
        await repo.create(entry)

        await repo.update_repo_status(
            entry.id,
            repo_status="ready",
            forgejo_repo_id=42,
            current_head_sha="abc123",
        )

        updated = await repo.get_by_id(entry.id)
        assert updated is not None
        assert updated.repo_status == "ready"
        assert updated.forgejo_repo_id == 42
        assert updated.current_head_sha == "abc123"

    async def test_update_nonexistent_is_noop(self, db_session: AsyncSession) -> None:
        repo = EntryRepository(db_session)
        # Should not raise
        await repo.update_repo_status(uuid4(), repo_status="ready")
