# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Integration tests for the tags extension repository (NEV-131).

Tests repository methods against a real database session.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.user import User
from phiacta.core.models.entry import Entry
from phiacta.extensions.tags.models import ExtensionTag  # noqa: F401 — register model
from tests.conftest import make_user, make_entry


async def _create_user_and_entry(
    db_session: AsyncSession,
    *,
    title: str = "Test Entry",
    status: str = "active",
) -> tuple[User, Entry]:
    """Helper: create a user and entry in the database."""
    suffix = uuid4().hex[:8]
    user = User(**make_user(handle=f"repo-test-{suffix}"))
    db_session.add(user)
    await db_session.flush()

    entry_kwargs = make_entry(created_by=user.id, title=title, status=status)
    # Remove 'tags' key if present (will be removed from make_entry later)
    entry_kwargs.pop("tags", None)
    entry = Entry(**entry_kwargs)
    db_session.add(entry)
    await db_session.flush()
    return user, entry


class TestListByEntry:
    """TagRepository.list_by_entry returns tags for a specific entry."""

    async def test_list_tags_for_entry(self, db_session: AsyncSession) -> None:
        """Returns tags associated with the given entry."""
        from phiacta.extensions.tags.repository import TagRepository

        user, entry = await _create_user_and_entry(db_session)
        repo = TagRepository(db_session)

        # Manually insert tags
        await repo.replace_tags(entry.id, ["physics", "math"], user.id)

        tags = await repo.list_by_entry(entry.id)
        tag_names = [t.tag for t in tags]
        assert "physics" in tag_names
        assert "math" in tag_names

    async def test_list_tags_for_unknown_entry(
        self, db_session: AsyncSession
    ) -> None:
        """Returns empty list for an entry with no tags (or unknown entry)."""
        from phiacta.extensions.tags.repository import TagRepository

        repo = TagRepository(db_session)
        tags = await repo.list_by_entry(uuid4())
        assert tags == []


class TestReplaceTags:
    """TagRepository.replace_tags atomically replaces all tags."""

    async def test_replace_tags_sets_new(
        self, db_session: AsyncSession
    ) -> None:
        """Setting tags on an entry with no tags creates the tags."""
        from phiacta.extensions.tags.repository import TagRepository

        user, entry = await _create_user_and_entry(db_session)
        repo = TagRepository(db_session)

        await repo.replace_tags(entry.id, ["alpha", "beta"], user.id)
        tags = await repo.list_by_entry(entry.id)
        assert len(tags) == 2
        tag_names = {t.tag for t in tags}
        assert tag_names == {"alpha", "beta"}

    async def test_replace_tags_removes_old(
        self, db_session: AsyncSession
    ) -> None:
        """Replacing tags removes old tags and sets new ones atomically."""
        from phiacta.extensions.tags.repository import TagRepository

        user, entry = await _create_user_and_entry(db_session)
        repo = TagRepository(db_session)

        await repo.replace_tags(entry.id, ["old1", "old2"], user.id)
        await repo.replace_tags(entry.id, ["new1"], user.id)

        tags = await repo.list_by_entry(entry.id)
        tag_names = {t.tag for t in tags}
        assert tag_names == {"new1"}
        assert "old1" not in tag_names
        assert "old2" not in tag_names

    async def test_replace_tags_with_empty_list_clears(
        self, db_session: AsyncSession
    ) -> None:
        """Replacing with an empty list removes all tags."""
        from phiacta.extensions.tags.repository import TagRepository

        user, entry = await _create_user_and_entry(db_session)
        repo = TagRepository(db_session)

        await repo.replace_tags(entry.id, ["to-clear"], user.id)
        await repo.replace_tags(entry.id, [], user.id)

        tags = await repo.list_by_entry(entry.id)
        assert tags == []

    async def test_replace_tags_records_created_by(
        self, db_session: AsyncSession
    ) -> None:
        """Each tag record has the correct created_by user ID."""
        from phiacta.extensions.tags.repository import TagRepository

        user, entry = await _create_user_and_entry(db_session)
        repo = TagRepository(db_session)

        await repo.replace_tags(entry.id, ["traced"], user.id)
        tags = await repo.list_by_entry(entry.id)
        assert tags[0].created_by == user.id


class TestFindEntriesByTags:
    """TagRepository.find_entries_by_tags searches across entries."""

    async def test_or_mode(self, db_session: AsyncSession) -> None:
        """OR mode returns entries with ANY matching tag."""
        from phiacta.extensions.tags.repository import TagRepository

        user, entry_a = await _create_user_and_entry(
            db_session, title="Entry A"
        )
        _, entry_b = await _create_user_and_entry(db_session, title="Entry B")

        repo = TagRepository(db_session)
        await repo.replace_tags(entry_a.id, ["physics"], user.id)
        await repo.replace_tags(entry_b.id, ["math"], user.id)

        results, total = await repo.find_entries_by_tags(
            tags=["physics", "math"], mode="or"
        )
        found_ids = {r.id for r in results}
        assert entry_a.id in found_ids
        assert entry_b.id in found_ids
        assert total >= 2

    async def test_and_mode(self, db_session: AsyncSession) -> None:
        """AND mode returns only entries with ALL matching tags."""
        from phiacta.extensions.tags.repository import TagRepository

        user, entry_both = await _create_user_and_entry(
            db_session, title="Both Tags"
        )
        _, entry_one = await _create_user_and_entry(
            db_session, title="One Tag"
        )

        repo = TagRepository(db_session)
        await repo.replace_tags(entry_both.id, ["physics", "math"], user.id)
        await repo.replace_tags(entry_one.id, ["physics"], user.id)

        results, total = await repo.find_entries_by_tags(
            tags=["physics", "math"], mode="and"
        )
        found_ids = {r.id for r in results}
        assert entry_both.id in found_ids
        assert entry_one.id not in found_ids

    async def test_no_matches(self, db_session: AsyncSession) -> None:
        """No matching tags returns empty results."""
        from phiacta.extensions.tags.repository import TagRepository

        repo = TagRepository(db_session)
        results, total = await repo.find_entries_by_tags(
            tags=["nonexistent"], mode="or"
        )
        assert results == []
        assert total == 0

    async def test_active_only_by_default(
        self, db_session: AsyncSession
    ) -> None:
        """Archived entries are excluded by default."""
        from phiacta.extensions.tags.repository import TagRepository

        user, entry = await _create_user_and_entry(
            db_session, title="Archived", status="archived"
        )
        repo = TagRepository(db_session)
        await repo.replace_tags(entry.id, ["archived-test"], user.id)

        results, total = await repo.find_entries_by_tags(
            tags=["archived-test"], mode="or", status="active"
        )
        found_ids = {r.id for r in results}
        assert entry.id not in found_ids

    async def test_include_archived(self, db_session: AsyncSession) -> None:
        """Archived entries are included when include_archived=True."""
        from phiacta.extensions.tags.repository import TagRepository

        user, entry = await _create_user_and_entry(
            db_session, title="Archived Included", status="archived"
        )
        repo = TagRepository(db_session)
        await repo.replace_tags(entry.id, ["archived-include"], user.id)

        results, total = await repo.find_entries_by_tags(
            tags=["archived-include"], mode="or", status=None
        )
        found_ids = {r.id for r in results}
        assert entry.id in found_ids

    async def test_pagination(self, db_session: AsyncSession) -> None:
        """find_entries_by_tags supports limit and offset."""
        from phiacta.extensions.tags.repository import TagRepository

        user, _ = await _create_user_and_entry(db_session)
        repo = TagRepository(db_session)

        entries = []
        for i in range(5):
            _, entry = await _create_user_and_entry(
                db_session, title=f"Page Entry {i}"
            )
            await repo.replace_tags(entry.id, ["page-test"], user.id)
            entries.append(entry)

        page1, total = await repo.find_entries_by_tags(
            tags=["page-test"], mode="or", limit=2, offset=0
        )
        assert len(page1) == 2
        assert total == 5

        page2, _ = await repo.find_entries_by_tags(
            tags=["page-test"], mode="or", limit=2, offset=2
        )
        assert len(page2) == 2

        # Pages should not overlap
        page1_ids = {r.id for r in page1}
        page2_ids = {r.id for r in page2}
        assert page1_ids.isdisjoint(page2_ids)
