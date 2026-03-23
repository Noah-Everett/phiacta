# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Integration tests for the EntityRepository.

Tests repository methods against a real database session (SQLite in-memory
or Postgres via TEST_DATABASE_URL).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# Models must be imported to register them with Base.metadata
from phiacta.core.models.entity import Entity  # noqa: F401
from phiacta.core.models.activity import Activity  # noqa: F401
from phiacta.core.models.user import User  # noqa: F401
from phiacta.core.models.entry import Entry  # noqa: F401
from phiacta.core.repositories.entity_repository import EntityRepository
from tests.conftest import make_user, make_entry


async def _create_user_entity(
    db_session: AsyncSession,
) -> Entity:
    """Create a user-type entity in the DB and return it."""
    repo = EntityRepository(db_session)
    entity = await repo.create(
        entity_type="user",
        parent_id=None,
        external_ref=None,
        created_by=None,
    )
    await db_session.flush()
    return entity


async def _create_entry_entity(
    db_session: AsyncSession,
    user_entity_id,
) -> Entity:
    """Create an entry-type entity with created_by set."""
    repo = EntityRepository(db_session)
    entity = await repo.create(
        entity_type="entry",
        parent_id=None,
        external_ref=None,
        created_by=user_entity_id,
    )
    await db_session.flush()
    return entity


class TestCreateEntity:
    """EntityRepository.create stores entities correctly."""

    async def test_create_user_entity(self, db_session: AsyncSession) -> None:
        """User entities have type='user', created_by=NULL."""
        repo = EntityRepository(db_session)
        entity = await repo.create(
            entity_type="user",
            parent_id=None,
            external_ref=None,
            created_by=None,
        )
        assert entity.id is not None
        assert entity.entity_type == "user"
        assert entity.parent_id is None
        assert entity.created_by is None
        assert entity.created_at is not None

    async def test_create_entry_entity(self, db_session: AsyncSession) -> None:
        """Entry entities have type='entry', created_by=user_entity_id."""
        user_entity = await _create_user_entity(db_session)
        repo = EntityRepository(db_session)
        entity = await repo.create(
            entity_type="entry",
            parent_id=None,
            external_ref=None,
            created_by=user_entity.id,
        )
        assert entity.entity_type == "entry"
        assert entity.created_by == user_entity.id
        assert entity.parent_id is None

    async def test_create_issue_entity_with_parent_and_ref(
        self, db_session: AsyncSession,
    ) -> None:
        """Issue entities have parent_id=entry_entity_id and external_ref."""
        user_entity = await _create_user_entity(db_session)
        entry_entity = await _create_entry_entity(db_session, user_entity.id)
        repo = EntityRepository(db_session)

        entity = await repo.create(
            entity_type="issue",
            parent_id=entry_entity.id,
            external_ref="issues/1",
            created_by=user_entity.id,
        )
        assert entity.entity_type == "issue"
        assert entity.parent_id == entry_entity.id
        assert entity.external_ref == "issues/1"

    async def test_create_edit_entity_with_parent_and_ref(
        self, db_session: AsyncSession,
    ) -> None:
        """Edit entities have parent_id=entry_entity_id and external_ref
        like 'pulls/N'."""
        user_entity = await _create_user_entity(db_session)
        entry_entity = await _create_entry_entity(db_session, user_entity.id)
        repo = EntityRepository(db_session)

        entity = await repo.create(
            entity_type="edit",
            parent_id=entry_entity.id,
            external_ref="pulls/1",
            created_by=user_entity.id,
        )
        assert entity.entity_type == "edit"
        assert entity.parent_id == entry_entity.id
        assert entity.external_ref == "pulls/1"

    async def test_create_comment_entity_with_issue_parent(
        self, db_session: AsyncSession,
    ) -> None:
        """Comment entities have parent_id=issue_entity_id."""
        user_entity = await _create_user_entity(db_session)
        entry_entity = await _create_entry_entity(db_session, user_entity.id)
        repo = EntityRepository(db_session)
        issue_entity = await repo.create(
            entity_type="issue",
            parent_id=entry_entity.id,
            external_ref="issues/1",
            created_by=user_entity.id,
        )
        await db_session.flush()

        comment_entity = await repo.create(
            entity_type="comment",
            parent_id=issue_entity.id,
            external_ref=None,
            created_by=user_entity.id,
        )
        assert comment_entity.entity_type == "comment"
        assert comment_entity.parent_id == issue_entity.id

    async def test_created_entity_has_unique_id(
        self, db_session: AsyncSession,
    ) -> None:
        """Each created entity gets a unique UUID."""
        repo = EntityRepository(db_session)
        e1 = await repo.create(
            entity_type="user", parent_id=None,
            external_ref=None, created_by=None,
        )
        e2 = await repo.create(
            entity_type="user", parent_id=None,
            external_ref=None, created_by=None,
        )
        assert e1.id != e2.id


class TestGetById:
    """EntityRepository.get_by_id returns the correct entity."""

    async def test_get_existing_entity(self, db_session: AsyncSession) -> None:
        entity = await _create_user_entity(db_session)
        repo = EntityRepository(db_session)
        fetched = await repo.get_by_id(entity.id)
        assert fetched is not None
        assert fetched.id == entity.id
        assert fetched.entity_type == "user"

    async def test_get_nonexistent_returns_none(
        self, db_session: AsyncSession,
    ) -> None:
        repo = EntityRepository(db_session)
        result = await repo.get_by_id(uuid4())
        assert result is None


class TestListByType:
    """EntityRepository.list_by_type filters by entity_type."""

    async def test_filter_by_type(self, db_session: AsyncSession) -> None:
        """Returns only entities of the requested type."""
        user = await _create_user_entity(db_session)
        await _create_entry_entity(db_session, user.id)
        await _create_entry_entity(db_session, user.id)

        repo = EntityRepository(db_session)
        users = await repo.list_by_type("user")
        entries = await repo.list_by_type("entry")

        assert all(e.entity_type == "user" for e in users)
        assert all(e.entity_type == "entry" for e in entries)
        assert len(entries) == 2

    async def test_empty_result(self, db_session: AsyncSession) -> None:
        repo = EntityRepository(db_session)
        result = await repo.list_by_type("comment")
        assert result == []


class TestListByParent:
    """EntityRepository.list_by_parent returns child entities."""

    async def test_returns_children(self, db_session: AsyncSession) -> None:
        user = await _create_user_entity(db_session)
        entry = await _create_entry_entity(db_session, user.id)
        repo = EntityRepository(db_session)

        # Create 2 issues as children of entry
        for i in range(2):
            await repo.create(
                entity_type="issue",
                parent_id=entry.id,
                external_ref=f"issues/{i + 1}",
                created_by=user.id,
            )
        await db_session.flush()

        children = await repo.list_by_parent(entry.id)
        assert len(children) == 2
        assert all(c.parent_id == entry.id for c in children)

    async def test_returns_empty_for_no_children(
        self, db_session: AsyncSession,
    ) -> None:
        user = await _create_user_entity(db_session)
        entry = await _create_entry_entity(db_session, user.id)
        repo = EntityRepository(db_session)
        children = await repo.list_by_parent(entry.id)
        assert children == []

    async def test_does_not_return_grandchildren(
        self, db_session: AsyncSession,
    ) -> None:
        """list_by_parent returns only direct children, not nested."""
        user = await _create_user_entity(db_session)
        entry = await _create_entry_entity(db_session, user.id)
        repo = EntityRepository(db_session)

        issue = await repo.create(
            entity_type="issue",
            parent_id=entry.id,
            external_ref="issues/1",
            created_by=user.id,
        )
        await db_session.flush()

        # Comment is a child of the issue, not the entry
        await repo.create(
            entity_type="comment",
            parent_id=issue.id,
            external_ref=None,
            created_by=user.id,
        )
        await db_session.flush()

        entry_children = await repo.list_by_parent(entry.id)
        assert len(entry_children) == 1
        assert entry_children[0].entity_type == "issue"


class TestGetByExternalRef:
    """EntityRepository.get_by_external_ref finds Forgejo-backed entities."""

    async def test_find_by_parent_and_ref(
        self, db_session: AsyncSession,
    ) -> None:
        user = await _create_user_entity(db_session)
        entry = await _create_entry_entity(db_session, user.id)
        repo = EntityRepository(db_session)

        await repo.create(
            entity_type="issue",
            parent_id=entry.id,
            external_ref="issues/42",
            created_by=user.id,
        )
        await db_session.flush()

        found = await repo.get_by_external_ref(entry.id, "issues/42")
        assert found is not None
        assert found.external_ref == "issues/42"
        assert found.parent_id == entry.id

    async def test_returns_none_for_nonexistent_ref(
        self, db_session: AsyncSession,
    ) -> None:
        user = await _create_user_entity(db_session)
        entry = await _create_entry_entity(db_session, user.id)
        repo = EntityRepository(db_session)
        found = await repo.get_by_external_ref(entry.id, "issues/999")
        assert found is None

    async def test_different_parents_same_ref(
        self, db_session: AsyncSession,
    ) -> None:
        """The same external_ref under different parents are distinct."""
        user = await _create_user_entity(db_session)
        entry_a = await _create_entry_entity(db_session, user.id)
        entry_b = await _create_entry_entity(db_session, user.id)
        repo = EntityRepository(db_session)

        await repo.create(
            entity_type="issue",
            parent_id=entry_a.id,
            external_ref="issues/1",
            created_by=user.id,
        )
        await repo.create(
            entity_type="issue",
            parent_id=entry_b.id,
            external_ref="issues/1",
            created_by=user.id,
        )
        await db_session.flush()

        found_a = await repo.get_by_external_ref(entry_a.id, "issues/1")
        found_b = await repo.get_by_external_ref(entry_b.id, "issues/1")
        assert found_a is not None
        assert found_b is not None
        assert found_a.id != found_b.id


class TestUniquePartialIndex:
    """The unique partial index on (parent_id, external_ref) WHERE
    external_ref IS NOT NULL prevents duplicate Forgejo-backed entities."""

    async def test_duplicate_external_ref_raises(
        self, db_session: AsyncSession,
    ) -> None:
        """Creating two entities with the same (parent_id, external_ref)
        should raise an IntegrityError."""
        user = await _create_user_entity(db_session)
        entry = await _create_entry_entity(db_session, user.id)
        repo = EntityRepository(db_session)

        await repo.create(
            entity_type="issue",
            parent_id=entry.id,
            external_ref="issues/1",
            created_by=user.id,
        )
        await db_session.flush()

        with pytest.raises(IntegrityError):
            await repo.create(
                entity_type="issue",
                parent_id=entry.id,
                external_ref="issues/1",
                created_by=user.id,
            )
            await db_session.flush()

    async def test_null_external_ref_allows_duplicates(
        self, db_session: AsyncSession,
    ) -> None:
        """Multiple entities with NULL external_ref on the same parent
        are allowed (partial index only applies to non-NULL)."""
        user = await _create_user_entity(db_session)
        entry = await _create_entry_entity(db_session, user.id)
        repo = EntityRepository(db_session)

        c1 = await repo.create(
            entity_type="comment",
            parent_id=entry.id,
            external_ref=None,
            created_by=user.id,
        )
        c2 = await repo.create(
            entity_type="comment",
            parent_id=entry.id,
            external_ref=None,
            created_by=user.id,
        )
        await db_session.flush()
        assert c1.id != c2.id
