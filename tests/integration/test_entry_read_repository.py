# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Integration tests for entry read repository methods (NEV-120).

Tests the repository-level behavior for listing and counting entries,
especially the changes needed for the read API:
- Default status filtering (active by default)
- status=None bypasses status filter
- Window-function-based list+count in a single query
- Correct count matching list result count
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.models.agent import Agent
from phiacta.models.entry import Entry
from phiacta.models.entry_ref import EntryRef
from phiacta.repositories.entry_ref_repository import EntryRefRepository
from phiacta.repositories.entry_repository import EntryRepository
from tests.conftest import make_agent, make_entry, make_entry_ref

needs_db = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="TEST_DATABASE_URL not set; skipping integration test",
)


async def _setup_agent(db_session: AsyncSession) -> Agent:
    """Create and flush a test agent."""
    agent = Agent(**make_agent(
        handle=f"read-repo-{uuid4().hex[:8]}",
        email=f"read-repo-{uuid4().hex[:8]}@example.com",
    ))
    db_session.add(agent)
    await db_session.flush()
    return agent


async def _create_entry(
    db_session: AsyncSession,
    repo: EntryRepository,
    agent: Agent,
    *,
    title: str = "Test Entry",
    layout_hint: str | None = None,
    status: str = "active",
    content_format: str = "markdown",
    tags: list[str] | None = None,
) -> Entry:
    """Create an entry in the DB and return it."""
    entry = Entry(
        **make_entry(
            created_by=agent.id,
            title=title,
            layout_hint=layout_hint,
            status=status,
            content_format=content_format,
            tags=tags,
        )
    )
    return await repo.create(entry)


@needs_db
class TestListEntriesDefaultStatus:
    """Repository list_entries defaults to status='active' when no status given."""

    async def test_list_entries_default_returns_only_active(
        self, db_session: AsyncSession
    ) -> None:
        """When status is not provided (or None/default), only active entries returned."""
        agent = await _setup_agent(db_session)
        repo = EntryRepository(db_session)

        active = await _create_entry(
            db_session, repo, agent, title="Active", status="active"
        )
        archived = await _create_entry(
            db_session, repo, agent, title="Archived", status="archived"
        )

        # Default call (no status param) should return only active
        entries = await repo.list_entries()
        entry_ids = {e.id for e in entries}
        assert active.id in entry_ids
        assert archived.id not in entry_ids

    async def test_list_entries_explicit_active(
        self, db_session: AsyncSession
    ) -> None:
        """Explicit status='active' behaves same as default."""
        agent = await _setup_agent(db_session)
        repo = EntryRepository(db_session)

        active = await _create_entry(
            db_session, repo, agent, title="Active Explicit", status="active"
        )
        archived = await _create_entry(
            db_session, repo, agent, title="Archived Explicit", status="archived"
        )

        entries = await repo.list_entries(status="active")
        entry_ids = {e.id for e in entries}
        assert active.id in entry_ids
        assert archived.id not in entry_ids


@needs_db
class TestListEntriesStatusAll:
    """Repository list_entries with status='all' returns all entries."""

    async def test_status_all_returns_active_and_archived(
        self, db_session: AsyncSession
    ) -> None:
        """status='all' bypasses status filtering entirely."""
        agent = await _setup_agent(db_session)
        repo = EntryRepository(db_session)

        active = await _create_entry(
            db_session, repo, agent, title="Active All", status="active"
        )
        archived = await _create_entry(
            db_session, repo, agent, title="Archived All", status="archived"
        )

        entries = await repo.list_entries(status=None)
        entry_ids = {e.id for e in entries}
        assert active.id in entry_ids
        assert archived.id in entry_ids

    async def test_status_all_with_layout_hint(
        self, db_session: AsyncSession
    ) -> None:
        """status='all' combined with layout_hint still filters by hint."""
        agent = await _setup_agent(db_session)
        repo = EntryRepository(db_session)

        active_law = await _create_entry(
            db_session, repo, agent, title="Active Law",
            layout_hint="law", status="active",
        )
        archived_law = await _create_entry(
            db_session, repo, agent, title="Archived Law",
            layout_hint="law", status="archived",
        )
        active_theorem = await _create_entry(
            db_session, repo, agent, title="Active Theorem",
            layout_hint="theorem", status="active",
        )

        entries = await repo.list_entries(status=None, layout_hint="law")
        entry_ids = {e.id for e in entries}
        assert active_law.id in entry_ids
        assert archived_law.id in entry_ids
        assert active_theorem.id not in entry_ids


@needs_db
class TestListEntriesStatusArchived:
    """Repository list_entries with status='archived' returns only archived."""

    async def test_status_archived_returns_only_archived(
        self, db_session: AsyncSession
    ) -> None:
        """Explicit status='archived' returns only archived entries."""
        agent = await _setup_agent(db_session)
        repo = EntryRepository(db_session)

        await _create_entry(
            db_session, repo, agent, title="Active Skip", status="active"
        )
        archived = await _create_entry(
            db_session, repo, agent, title="Archived Only", status="archived"
        )

        entries = await repo.list_entries(status="archived")
        entry_ids = {e.id for e in entries}
        assert archived.id in entry_ids
        for e in entries:
            assert e.status == "archived"


@needs_db
class TestCountEntriesMatchesList:
    """count_entries must match the count of entries returned by list_entries."""

    async def test_count_matches_list_default_status(
        self, db_session: AsyncSession
    ) -> None:
        """Count with default status matches list with default status."""
        agent = await _setup_agent(db_session)
        repo = EntryRepository(db_session)

        for i in range(3):
            await _create_entry(
                db_session, repo, agent, title=f"Count Active {i}", status="active"
            )
        await _create_entry(
            db_session, repo, agent, title="Count Archived", status="archived"
        )

        entries = await repo.list_entries()
        count = await repo.count_entries()
        assert count == len(entries)
        assert count == 3  # Only active

    async def test_count_matches_list_status_all(
        self, db_session: AsyncSession
    ) -> None:
        """Count with status='all' matches list with status='all'."""
        agent = await _setup_agent(db_session)
        repo = EntryRepository(db_session)

        for i in range(2):
            await _create_entry(
                db_session, repo, agent, title=f"All Active {i}", status="active"
            )
        await _create_entry(
            db_session, repo, agent, title="All Archived", status="archived"
        )

        entries = await repo.list_entries(status=None)
        count = await repo.count_entries(status=None)
        assert count == len(entries)
        assert count == 3

    async def test_count_matches_list_with_layout_hint(
        self, db_session: AsyncSession
    ) -> None:
        """Count and list agree when filtered by layout_hint."""
        agent = await _setup_agent(db_session)
        repo = EntryRepository(db_session)

        for i in range(3):
            await _create_entry(
                db_session, repo, agent,
                title=f"Law {i}", layout_hint="law",
            )
        await _create_entry(
            db_session, repo, agent,
            title="Theorem", layout_hint="theorem",
        )

        entries = await repo.list_entries(layout_hint="law")
        count = await repo.count_entries(layout_hint="law")
        assert count == len(entries)
        assert count == 3

    async def test_count_matches_list_with_status_archived(
        self, db_session: AsyncSession
    ) -> None:
        """Count and list agree for status='archived'."""
        agent = await _setup_agent(db_session)
        repo = EntryRepository(db_session)

        await _create_entry(
            db_session, repo, agent, title="Active", status="active"
        )
        for i in range(2):
            await _create_entry(
                db_session, repo, agent,
                title=f"Archived {i}", status="archived",
            )

        entries = await repo.list_entries(status="archived")
        count = await repo.count_entries(status="archived")
        assert count == len(entries)
        assert count == 2


@needs_db
class TestListEntriesOrdering:
    """Entries are returned ordered by created_at DESC."""

    async def test_list_entries_newest_first(
        self, db_session: AsyncSession
    ) -> None:
        """Entries created later appear first in the list."""
        agent = await _setup_agent(db_session)
        repo = EntryRepository(db_session)

        first = await _create_entry(
            db_session, repo, agent, title="First"
        )
        second = await _create_entry(
            db_session, repo, agent, title="Second"
        )
        third = await _create_entry(
            db_session, repo, agent, title="Third"
        )

        entries = await repo.list_entries()
        assert len(entries) >= 3
        # Find our entries in the list and verify ordering
        our_entries = [e for e in entries if e.id in {first.id, second.id, third.id}]
        assert len(our_entries) == 3
        assert our_entries[0].id == third.id
        assert our_entries[1].id == second.id
        assert our_entries[2].id == first.id


@needs_db
class TestListEntriesPaginationIntegration:
    """Pagination at repository level."""

    async def test_limit_and_offset(self, db_session: AsyncSession) -> None:
        """limit and offset produce correct slices."""
        agent = await _setup_agent(db_session)
        repo = EntryRepository(db_session)

        created = []
        for i in range(5):
            e = await _create_entry(
                db_session, repo, agent, title=f"Page Entry {i}"
            )
            created.append(e)

        page1 = await repo.list_entries(limit=2, offset=0)
        page2 = await repo.list_entries(limit=2, offset=2)
        page3 = await repo.list_entries(limit=2, offset=4)

        assert len(page1) == 2
        assert len(page2) == 2
        assert len(page3) == 1

        all_ids = {e.id for e in page1} | {e.id for e in page2} | {e.id for e in page3}
        assert len(all_ids) == 5

    async def test_offset_beyond_total(self, db_session: AsyncSession) -> None:
        """Offset beyond total returns empty list."""
        agent = await _setup_agent(db_session)
        repo = EntryRepository(db_session)

        await _create_entry(db_session, repo, agent, title="Only One")

        entries = await repo.list_entries(limit=10, offset=100)
        assert entries == []


@needs_db
class TestGetByIdFields:
    """get_by_id returns an entry with all correct fields."""

    async def test_get_by_id_returns_all_fields(
        self, db_session: AsyncSession
    ) -> None:
        """Fetched entry has all expected model fields populated."""
        agent = await _setup_agent(db_session)
        repo = EntryRepository(db_session)

        entry = await _create_entry(
            db_session, repo, agent,
            title="Full Fields Entry",
            layout_hint="paper",
            content_format="latex",
            tags=["test", "integration"],
        )

        fetched = await repo.get_by_id(entry.id)
        assert fetched is not None
        assert fetched.id == entry.id
        assert fetched.title == "Full Fields Entry"
        assert fetched.layout_hint == "paper"
        assert fetched.content_format == "latex"
        assert fetched.tags == ["test", "integration"]
        assert fetched.status == "active"
        assert fetched.repo_status == "provisioning"
        assert fetched.schema_version == 1
        assert fetched.created_by == agent.id
        assert fetched.created_at is not None
        assert fetched.updated_at is not None

    async def test_get_by_id_nonexistent(
        self, db_session: AsyncSession
    ) -> None:
        """get_by_id with unknown UUID returns None."""
        repo = EntryRepository(db_session)
        result = await repo.get_by_id(uuid4())
        assert result is None


@needs_db
class TestEntryRefListByEntryForDetail:
    """EntryRefRepository.list_by_entry used by detail endpoint for ref fetching."""

    async def test_list_by_entry_outgoing_only(
        self, db_session: AsyncSession
    ) -> None:
        """direction='outgoing' returns only refs where from_entry_id matches."""
        agent = await _setup_agent(db_session)
        entry_repo = EntryRepository(db_session)
        ref_repo = EntryRefRepository(db_session)

        source = await _create_entry(
            db_session, entry_repo, agent, title="Ref Source"
        )
        target = await _create_entry(
            db_session, entry_repo, agent, title="Ref Target"
        )

        ref = EntryRef(
            **make_entry_ref(
                from_entry_id=source.id,
                to_entry_id=target.id,
                rel="cites",
            )
        )
        await ref_repo.create(ref)

        outgoing = await ref_repo.list_by_entry(source.id, direction="outgoing")
        assert len(outgoing) == 1
        assert outgoing[0].from_entry_id == source.id

        incoming_from_source = await ref_repo.list_by_entry(
            source.id, direction="incoming"
        )
        assert len(incoming_from_source) == 0

    async def test_list_by_entry_incoming_only(
        self, db_session: AsyncSession
    ) -> None:
        """direction='incoming' returns only refs where to_entry_id matches."""
        agent = await _setup_agent(db_session)
        entry_repo = EntryRepository(db_session)
        ref_repo = EntryRefRepository(db_session)

        source = await _create_entry(
            db_session, entry_repo, agent, title="Incoming Source"
        )
        target = await _create_entry(
            db_session, entry_repo, agent, title="Incoming Target"
        )

        ref = EntryRef(
            **make_entry_ref(
                from_entry_id=source.id,
                to_entry_id=target.id,
                rel="evidence",
            )
        )
        await ref_repo.create(ref)

        incoming = await ref_repo.list_by_entry(target.id, direction="incoming")
        assert len(incoming) == 1
        assert incoming[0].to_entry_id == target.id

        outgoing_from_target = await ref_repo.list_by_entry(
            target.id, direction="outgoing"
        )
        assert len(outgoing_from_target) == 0

    async def test_list_by_entry_multiple_refs(
        self, db_session: AsyncSession
    ) -> None:
        """Multiple refs in both directions are correctly separated."""
        agent = await _setup_agent(db_session)
        entry_repo = EntryRepository(db_session)
        ref_repo = EntryRefRepository(db_session)

        hub = await _create_entry(
            db_session, entry_repo, agent, title="Hub"
        )
        target_a = await _create_entry(
            db_session, entry_repo, agent, title="Target A"
        )
        target_b = await _create_entry(
            db_session, entry_repo, agent, title="Target B"
        )
        source_c = await _create_entry(
            db_session, entry_repo, agent, title="Source C"
        )

        # hub -> target_a, hub -> target_b (outgoing)
        await ref_repo.create(EntryRef(
            **make_entry_ref(from_entry_id=hub.id, to_entry_id=target_a.id, rel="cites")
        ))
        await ref_repo.create(EntryRef(
            **make_entry_ref(from_entry_id=hub.id, to_entry_id=target_b.id, rel="extends")
        ))
        # source_c -> hub (incoming)
        await ref_repo.create(EntryRef(
            **make_entry_ref(from_entry_id=source_c.id, to_entry_id=hub.id, rel="evidence")
        ))

        outgoing = await ref_repo.list_by_entry(hub.id, direction="outgoing")
        incoming = await ref_repo.list_by_entry(hub.id, direction="incoming")

        assert len(outgoing) == 2
        assert all(r.from_entry_id == hub.id for r in outgoing)
        assert len(incoming) == 1
        assert incoming[0].from_entry_id == source_c.id
