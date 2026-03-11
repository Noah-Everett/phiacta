# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.models.agent import Agent
from phiacta.models.entry import Entry
from phiacta.models.entry_ref import EntryRef
from phiacta.repositories.entry_ref_repository import EntryRefRepository
from tests.conftest import make_agent, make_entry, make_entry_ref

needs_db = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="TEST_DATABASE_URL not set; skipping integration test",
)


async def _setup_entries(
    db_session: AsyncSession,
) -> tuple[Agent, Entry, Entry]:
    """Create prerequisite agent and two entries."""
    agent = Agent(**make_agent())
    db_session.add(agent)
    await db_session.flush()

    entry_a = Entry(**make_entry(created_by=agent.id, title="Entry A"))
    entry_b = Entry(**make_entry(created_by=agent.id, title="Entry B"))
    db_session.add(entry_a)
    db_session.add(entry_b)
    await db_session.flush()
    return agent, entry_a, entry_b


@needs_db
class TestCreateAndGetEntryRef:
    async def test_create_and_get_entry_ref(self, db_session: AsyncSession) -> None:
        _agent, entry_a, entry_b = await _setup_entries(db_session)

        repo = EntryRefRepository(db_session)
        ref = EntryRef(
            **make_entry_ref(
                from_entry_id=entry_a.id,
                to_entry_id=entry_b.id,
                rel="evidence",
            )
        )
        created = await repo.create(ref)
        assert created.id == ref.id

        fetched = await repo.get_by_id(ref.id)
        assert fetched is not None
        assert fetched.from_entry_id == entry_a.id
        assert fetched.to_entry_id == entry_b.id
        assert fetched.rel == "evidence"


@needs_db
class TestListByEntryDirection:
    async def test_list_by_entry_both(self, db_session: AsyncSession) -> None:
        _agent, entry_a, entry_b = await _setup_entries(db_session)

        repo = EntryRefRepository(db_session)
        ref = EntryRef(
            **make_entry_ref(
                from_entry_id=entry_a.id,
                to_entry_id=entry_b.id,
                rel="evidence",
            )
        )
        await repo.create(ref)

        refs_a = await repo.list_by_entry(entry_a.id, direction="both")
        assert len(refs_a) >= 1

        refs_b = await repo.list_by_entry(entry_b.id, direction="both")
        assert len(refs_b) >= 1

    async def test_list_by_entry_outgoing(self, db_session: AsyncSession) -> None:
        _agent, entry_a, entry_b = await _setup_entries(db_session)

        repo = EntryRefRepository(db_session)
        ref = EntryRef(
            **make_entry_ref(
                from_entry_id=entry_a.id,
                to_entry_id=entry_b.id,
                rel="evidence",
            )
        )
        await repo.create(ref)

        outgoing = await repo.list_by_entry(entry_a.id, direction="outgoing")
        assert len(outgoing) >= 1
        assert all(r.from_entry_id == entry_a.id for r in outgoing)

        outgoing_b = await repo.list_by_entry(entry_b.id, direction="outgoing")
        assert len(outgoing_b) == 0

    async def test_list_by_entry_incoming(self, db_session: AsyncSession) -> None:
        _agent, entry_a, entry_b = await _setup_entries(db_session)

        repo = EntryRefRepository(db_session)
        ref = EntryRef(
            **make_entry_ref(
                from_entry_id=entry_a.id,
                to_entry_id=entry_b.id,
                rel="evidence",
            )
        )
        await repo.create(ref)

        incoming = await repo.list_by_entry(entry_b.id, direction="incoming")
        assert len(incoming) >= 1
        assert all(r.to_entry_id == entry_b.id for r in incoming)


@needs_db
class TestListByRel:
    async def test_list_by_rel(self, db_session: AsyncSession) -> None:
        _agent, entry_a, entry_b = await _setup_entries(db_session)

        repo = EntryRefRepository(db_session)
        ref1 = EntryRef(
            **make_entry_ref(
                from_entry_id=entry_a.id,
                to_entry_id=entry_b.id,
                rel="evidence",
            )
        )
        ref2 = EntryRef(
            **make_entry_ref(
                from_entry_id=entry_b.id,
                to_entry_id=entry_a.id,
                rel="derives_from",
            )
        )
        await repo.create(ref1)
        await repo.create(ref2)

        evidence = await repo.list_by_rel("evidence")
        assert len(evidence) >= 1
        assert all(r.rel == "evidence" for r in evidence)

        derives = await repo.list_by_rel("derives_from")
        assert len(derives) >= 1
        assert all(r.rel == "derives_from" for r in derives)
