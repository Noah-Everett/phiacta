# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Integration tests for the ActivityRepository.

Tests cursor-based pagination and query methods against a real database
session.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

# Register models with Base.metadata
from phiacta.core.models.entity import Entity  # noqa: F401
from phiacta.core.models.activity import Activity  # noqa: F401
from phiacta.core.repositories.entity_repository import EntityRepository
from phiacta.core.repositories.activity_repository import ActivityRepository


async def _create_actor_and_entity(
    db_session: AsyncSession,
) -> tuple:
    """Create a user entity and an entry entity, return (actor_id, entity_id)."""
    entity_repo = EntityRepository(db_session)

    actor = await entity_repo.create(
        entity_type="user",
        parent_id=None,
        external_ref=None,
        created_by=None,
    )
    await db_session.flush()

    entity = await entity_repo.create(
        entity_type="entry",
        parent_id=None,
        external_ref=None,
        created_by=actor.id,
    )
    await db_session.flush()
    return actor.id, entity.id


class TestLogActivity:
    """ActivityRepository.log stores activity records."""

    async def test_log_creates_record(self, db_session: AsyncSession) -> None:
        actor_id, entity_id = await _create_actor_and_entity(db_session)
        repo = ActivityRepository(db_session)

        activity = await repo.log(
            actor_id=actor_id,
            action="entry.created",
            entity_id=entity_id,
            metadata={"title": "Test"},
        )
        assert activity.id is not None
        assert activity.actor_id == actor_id
        assert activity.action == "entry.created"
        assert activity.entity_id == entity_id
        assert activity.activity_metadata == {"title": "Test"}
        assert activity.created_at is not None

    async def test_log_with_null_metadata(
        self, db_session: AsyncSession,
    ) -> None:
        actor_id, entity_id = await _create_actor_and_entity(db_session)
        repo = ActivityRepository(db_session)

        activity = await repo.log(
            actor_id=actor_id,
            action="entry.archived",
            entity_id=entity_id,
            metadata=None,
        )
        assert activity.activity_metadata is None

    async def test_log_preserves_complex_metadata(
        self, db_session: AsyncSession,
    ) -> None:
        """Metadata with nested structures is preserved correctly."""
        actor_id, entity_id = await _create_actor_and_entity(db_session)
        repo = ActivityRepository(db_session)

        complex_metadata = {
            "title": "Bug report",
            "entry_title": "Quantum Gravity",
            "tags": ["physics", "theory"],
        }
        activity = await repo.log(
            actor_id=actor_id,
            action="issue.created",
            entity_id=entity_id,
            metadata=complex_metadata,
        )
        assert activity.activity_metadata == complex_metadata
        assert activity.activity_metadata["tags"] == ["physics", "theory"]


class TestListByActor:
    """ActivityRepository.list_by_actor returns paginated results."""

    async def test_returns_activities_for_actor(
        self, db_session: AsyncSession,
    ) -> None:
        actor_id, entity_id = await _create_actor_and_entity(db_session)
        repo = ActivityRepository(db_session)

        for i in range(3):
            await repo.log(
                actor_id=actor_id,
                action="entry.created",
                entity_id=entity_id,
                metadata=None,
            )
        await db_session.flush()

        items, next_cursor = await repo.list_by_actor(actor_id, limit=50)
        assert len(items) == 3

    async def test_descending_order(
        self, db_session: AsyncSession,
    ) -> None:
        """Results are in descending created_at order (newest first)."""
        actor_id, entity_id = await _create_actor_and_entity(db_session)
        repo = ActivityRepository(db_session)

        actions = ["entry.created", "entry.archived", "entry.unarchived"]
        for action in actions:
            await repo.log(
                actor_id=actor_id,
                action=action,
                entity_id=entity_id,
                metadata=None,
            )
        await db_session.flush()

        items, _ = await repo.list_by_actor(actor_id, limit=50)
        timestamps = [a.created_at for a in items]
        assert timestamps == sorted(timestamps, reverse=True)

    async def test_limit_respected(
        self, db_session: AsyncSession,
    ) -> None:
        actor_id, entity_id = await _create_actor_and_entity(db_session)
        repo = ActivityRepository(db_session)

        for _ in range(5):
            await repo.log(
                actor_id=actor_id,
                action="entry.created",
                entity_id=entity_id,
                metadata=None,
            )
        await db_session.flush()

        items, next_cursor = await repo.list_by_actor(actor_id, limit=2)
        assert len(items) == 2
        assert next_cursor is not None

    async def test_cursor_pagination(
        self, db_session: AsyncSession,
    ) -> None:
        """Cursor-based pagination returns correct subsequent pages."""
        actor_id, entity_id = await _create_actor_and_entity(db_session)
        repo = ActivityRepository(db_session)

        for _ in range(5):
            await repo.log(
                actor_id=actor_id,
                action="entry.created",
                entity_id=entity_id,
                metadata=None,
            )
        await db_session.flush()

        # Page 1
        page1, cursor1 = await repo.list_by_actor(actor_id, limit=2)
        assert len(page1) == 2
        assert cursor1 is not None

        # Page 2
        page2, cursor2 = await repo.list_by_actor(
            actor_id, limit=2, before=cursor1,
        )
        assert len(page2) == 2
        assert cursor2 is not None

        # Page 3 (last item)
        page3, cursor3 = await repo.list_by_actor(
            actor_id, limit=2, before=cursor2,
        )
        assert len(page3) == 1
        assert cursor3 is None

        # No overlap
        all_ids = [a.id for a in page1 + page2 + page3]
        assert len(set(all_ids)) == 5

    async def test_empty_result(self, db_session: AsyncSession) -> None:
        """Actor with no activity returns empty list and null cursor."""
        entity_repo = EntityRepository(db_session)
        actor = await entity_repo.create(
            entity_type="user", parent_id=None,
            external_ref=None, created_by=None,
        )
        await db_session.flush()

        repo = ActivityRepository(db_session)
        items, cursor = await repo.list_by_actor(actor.id, limit=50)
        assert items == []
        assert cursor is None

    async def test_different_actors_isolated(
        self, db_session: AsyncSession,
    ) -> None:
        """list_by_actor only returns activities for the specified actor."""
        entity_repo = EntityRepository(db_session)
        actor_a = await entity_repo.create(
            entity_type="user", parent_id=None,
            external_ref=None, created_by=None,
        )
        actor_b = await entity_repo.create(
            entity_type="user", parent_id=None,
            external_ref=None, created_by=None,
        )
        entity = await entity_repo.create(
            entity_type="entry", parent_id=None,
            external_ref=None, created_by=actor_a.id,
        )
        await db_session.flush()

        repo = ActivityRepository(db_session)
        await repo.log(
            actor_id=actor_a.id, action="entry.created",
            entity_id=entity.id, metadata=None,
        )
        await repo.log(
            actor_id=actor_b.id, action="entry.created",
            entity_id=entity.id, metadata=None,
        )
        await db_session.flush()

        a_items, _ = await repo.list_by_actor(actor_a.id, limit=50)
        b_items, _ = await repo.list_by_actor(actor_b.id, limit=50)
        assert len(a_items) == 1
        assert len(b_items) == 1
        assert a_items[0].actor_id == actor_a.id
        assert b_items[0].actor_id == actor_b.id


class TestListByEntity:
    """ActivityRepository.list_by_entity returns activity for an entity."""

    async def test_returns_activities_for_entity(
        self, db_session: AsyncSession,
    ) -> None:
        actor_id, entity_id = await _create_actor_and_entity(db_session)
        repo = ActivityRepository(db_session)

        await repo.log(
            actor_id=actor_id, action="entry.created",
            entity_id=entity_id, metadata=None,
        )
        await repo.log(
            actor_id=actor_id, action="entry.archived",
            entity_id=entity_id, metadata=None,
        )
        await db_session.flush()

        items = await repo.list_by_entity(entity_id)
        assert len(items) == 2
        assert all(a.entity_id == entity_id for a in items)

    async def test_returns_empty_for_unknown_entity(
        self, db_session: AsyncSession,
    ) -> None:
        repo = ActivityRepository(db_session)
        items = await repo.list_by_entity(uuid4())
        assert items == []

    async def test_multiple_actors_on_same_entity(
        self, db_session: AsyncSession,
    ) -> None:
        """list_by_entity returns activity from ALL actors on that entity."""
        entity_repo = EntityRepository(db_session)
        actor_a = await entity_repo.create(
            entity_type="user", parent_id=None,
            external_ref=None, created_by=None,
        )
        actor_b = await entity_repo.create(
            entity_type="user", parent_id=None,
            external_ref=None, created_by=None,
        )
        entity = await entity_repo.create(
            entity_type="entry", parent_id=None,
            external_ref=None, created_by=actor_a.id,
        )
        await db_session.flush()

        repo = ActivityRepository(db_session)
        await repo.log(
            actor_id=actor_a.id, action="entry.created",
            entity_id=entity.id, metadata=None,
        )
        await repo.log(
            actor_id=actor_b.id, action="entry.archived",
            entity_id=entity.id, metadata=None,
        )
        await db_session.flush()

        items = await repo.list_by_entity(entity.id)
        assert len(items) == 2
        actor_ids = {a.actor_id for a in items}
        assert actor_a.id in actor_ids
        assert actor_b.id in actor_ids


class TestCountByActor:
    """ActivityRepository.count_by_actor returns correct counts."""

    async def test_count_matches_logged_activities(
        self, db_session: AsyncSession,
    ) -> None:
        actor_id, entity_id = await _create_actor_and_entity(db_session)
        repo = ActivityRepository(db_session)

        for _ in range(4):
            await repo.log(
                actor_id=actor_id, action="entry.created",
                entity_id=entity_id, metadata=None,
            )
        await db_session.flush()

        count = await repo.count_by_actor(actor_id)
        assert count == 4

    async def test_count_zero_for_new_actor(
        self, db_session: AsyncSession,
    ) -> None:
        entity_repo = EntityRepository(db_session)
        actor = await entity_repo.create(
            entity_type="user", parent_id=None,
            external_ref=None, created_by=None,
        )
        await db_session.flush()

        repo = ActivityRepository(db_session)
        count = await repo.count_by_actor(actor.id)
        assert count == 0

    async def test_count_excludes_other_actors(
        self, db_session: AsyncSession,
    ) -> None:
        """count_by_actor only counts the specified actor's activities."""
        entity_repo = EntityRepository(db_session)
        actor_a = await entity_repo.create(
            entity_type="user", parent_id=None,
            external_ref=None, created_by=None,
        )
        actor_b = await entity_repo.create(
            entity_type="user", parent_id=None,
            external_ref=None, created_by=None,
        )
        entity = await entity_repo.create(
            entity_type="entry", parent_id=None,
            external_ref=None, created_by=actor_a.id,
        )
        await db_session.flush()

        repo = ActivityRepository(db_session)
        for _ in range(3):
            await repo.log(
                actor_id=actor_a.id, action="entry.created",
                entity_id=entity.id, metadata=None,
            )
        await repo.log(
            actor_id=actor_b.id, action="entry.created",
            entity_id=entity.id, metadata=None,
        )
        await db_session.flush()

        assert await repo.count_by_actor(actor_a.id) == 3
        assert await repo.count_by_actor(actor_b.id) == 1
