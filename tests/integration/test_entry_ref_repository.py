# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.user import User
from phiacta.core.models.entry import Entry
from phiacta.core.models.entry_ref import EntryRef
from phiacta.core.repositories.entry_ref_repository import EntryRefRepository
from tests.conftest import make_user, make_entry, make_entry_ref

needs_db = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="TEST_DATABASE_URL not set; skipping integration test",
)


async def _setup_entries(
    db_session: AsyncSession,
) -> tuple[User, Entry, Entry]:
    """Create prerequisite user and two entries."""
    user = User(**make_user())
    db_session.add(user)
    await db_session.flush()

    entry_a = Entry(**make_entry(created_by=user.id, title="Entry A"))
    entry_b = Entry(**make_entry(created_by=user.id, title="Entry B"))
    db_session.add(entry_a)
    db_session.add(entry_b)
    await db_session.flush()
    return user, entry_a, entry_b


@needs_db
class TestCreateAndGetEntryRef:
    async def test_create_and_get_entry_ref(self, db_session: AsyncSession) -> None:
        _user, entry_a, entry_b = await _setup_entries(db_session)

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
        _user, entry_a, entry_b = await _setup_entries(db_session)

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
        _user, entry_a, entry_b = await _setup_entries(db_session)

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
        _user, entry_a, entry_b = await _setup_entries(db_session)

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
        _user, entry_a, entry_b = await _setup_entries(db_session)

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


# ---------------------------------------------------------------------------
# NEV-119: delete_outgoing
# ---------------------------------------------------------------------------


async def _setup_three_entries(
    db_session: AsyncSession,
) -> tuple[User, Entry, Entry, Entry]:
    """Create prerequisite user and three entries."""
    user = User(**make_user(handle="ref-del-user"))
    db_session.add(user)
    await db_session.flush()

    entry_a = Entry(**make_entry(created_by=user.id, title="Entry A"))
    entry_b = Entry(**make_entry(created_by=user.id, title="Entry B"))
    entry_c = Entry(**make_entry(created_by=user.id, title="Entry C"))
    db_session.add(entry_a)
    db_session.add(entry_b)
    db_session.add(entry_c)
    await db_session.flush()
    return user, entry_a, entry_b, entry_c


@needs_db
class TestDeleteOutgoing:
    """Tests for delete_outgoing(entry_id) -- NEV-119.

    This method deletes all outgoing entry_refs for a given entry
    (where from_entry_id == entry_id). It is used during refs.yaml
    ingestion to implement replace-all semantics.
    """

    async def test_delete_outgoing_removes_all_outgoing_refs(
        self, db_session: AsyncSession
    ) -> None:
        """delete_outgoing removes all refs where from_entry_id matches."""
        _user, entry_a, entry_b, entry_c = await _setup_three_entries(db_session)
        repo = EntryRefRepository(db_session)

        # Create two outgoing refs from entry_a
        ref1 = EntryRef(
            **make_entry_ref(from_entry_id=entry_a.id, to_entry_id=entry_b.id, rel="cites")
        )
        ref2 = EntryRef(
            **make_entry_ref(from_entry_id=entry_a.id, to_entry_id=entry_c.id, rel="extends")
        )
        await repo.create(ref1)
        await repo.create(ref2)

        # Verify refs exist
        outgoing = await repo.list_by_entry(entry_a.id, direction="outgoing")
        assert len(outgoing) == 2

        # Delete outgoing
        await repo.delete_outgoing(entry_a.id)

        # Verify refs are gone
        outgoing_after = await repo.list_by_entry(entry_a.id, direction="outgoing")
        assert len(outgoing_after) == 0

    async def test_delete_outgoing_does_not_affect_incoming_refs(
        self, db_session: AsyncSession
    ) -> None:
        """delete_outgoing does NOT remove incoming refs (to_entry_id matches)."""
        _user, entry_a, entry_b, entry_c = await _setup_three_entries(db_session)
        repo = EntryRefRepository(db_session)

        # entry_b -> entry_a (incoming to A)
        ref_incoming = EntryRef(
            **make_entry_ref(from_entry_id=entry_b.id, to_entry_id=entry_a.id, rel="cites")
        )
        # entry_a -> entry_c (outgoing from A)
        ref_outgoing = EntryRef(
            **make_entry_ref(from_entry_id=entry_a.id, to_entry_id=entry_c.id, rel="extends")
        )
        await repo.create(ref_incoming)
        await repo.create(ref_outgoing)

        # Delete outgoing from A
        await repo.delete_outgoing(entry_a.id)

        # Incoming ref to A should still exist
        incoming = await repo.list_by_entry(entry_a.id, direction="incoming")
        assert len(incoming) == 1
        assert incoming[0].from_entry_id == entry_b.id

        # Outgoing from A should be gone
        outgoing = await repo.list_by_entry(entry_a.id, direction="outgoing")
        assert len(outgoing) == 0

    async def test_delete_outgoing_does_not_affect_other_entries_refs(
        self, db_session: AsyncSession
    ) -> None:
        """delete_outgoing for entry_a does not touch entry_b's outgoing refs."""
        _user, entry_a, entry_b, entry_c = await _setup_three_entries(db_session)
        repo = EntryRefRepository(db_session)

        # entry_a -> entry_c
        ref_a = EntryRef(
            **make_entry_ref(from_entry_id=entry_a.id, to_entry_id=entry_c.id, rel="cites")
        )
        # entry_b -> entry_c
        ref_b = EntryRef(
            **make_entry_ref(from_entry_id=entry_b.id, to_entry_id=entry_c.id, rel="extends")
        )
        await repo.create(ref_a)
        await repo.create(ref_b)

        # Delete outgoing from A only
        await repo.delete_outgoing(entry_a.id)

        # B's ref should still exist
        outgoing_b = await repo.list_by_entry(entry_b.id, direction="outgoing")
        assert len(outgoing_b) == 1
        assert outgoing_b[0].rel == "extends"

    async def test_delete_outgoing_noop_when_no_refs_exist(
        self, db_session: AsyncSession
    ) -> None:
        """delete_outgoing on an entry with no outgoing refs does not raise."""
        _user, entry_a, _entry_b, _entry_c = await _setup_three_entries(db_session)
        repo = EntryRefRepository(db_session)

        # No refs created -- should not raise
        await repo.delete_outgoing(entry_a.id)

        # Still no refs
        outgoing = await repo.list_by_entry(entry_a.id, direction="outgoing")
        assert len(outgoing) == 0

    async def test_delete_outgoing_returns_count_or_none(
        self, db_session: AsyncSession
    ) -> None:
        """delete_outgoing completes without error and the refs are actually gone."""
        _user, entry_a, entry_b, entry_c = await _setup_three_entries(db_session)
        repo = EntryRefRepository(db_session)

        # Create 3 outgoing refs
        for target in [entry_b, entry_c]:
            ref = EntryRef(
                **make_entry_ref(from_entry_id=entry_a.id, to_entry_id=target.id, rel="cites")
            )
            await repo.create(ref)

        await repo.delete_outgoing(entry_a.id)

        # Verify count is 0
        count = await repo.count_by_entry(entry_a.id, direction="outgoing")
        assert count == 0
