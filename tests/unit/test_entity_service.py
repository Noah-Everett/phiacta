# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for EntityService.

Focused on the higher-level helpers callers use from API handlers,
particularly ``register_comment_and_log`` whose ``action`` parameter
must be respected so the activity feed reflects the correct event
type when commenting on an edit proposal vs. an issue.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Models must be imported to register them with Base.metadata
from phiacta.core.models.activity import Activity
from phiacta.core.models.entity import Entity  # noqa: F401
from phiacta.core.models.entry import Entry
from phiacta.core.models.user import User
from phiacta.core.repositories.entity_repository import EntityRepository
from phiacta.core.services.entity_service import EntityService
from tests.conftest import make_entry, make_user


async def _seed_user_and_entry(db: AsyncSession) -> tuple[User, Entry]:
    """Seed a user, an entry, and their entities. Returns (user, entry)."""
    user = User(**make_user())
    db.add(user)
    await db.flush()
    entry = Entry(**make_entry(created_by=user.id))
    db.add(entry)
    await db.flush()

    repo = EntityRepository(db)
    # Mirror the production shared-PK strategy: entity row shares the
    # user/entry's UUID for canonical lookups.
    await repo.create(
        entity_type="user",
        id=user.id,
        parent_id=None,
        external_ref=None,
        created_by=user.id,
    )
    await repo.create(
        entity_type="entry",
        id=entry.id,
        parent_id=user.id,
        external_ref=None,
        created_by=user.id,
    )
    await db.flush()
    return user, entry


class TestRegisterCommentAndLog:
    """register_comment_and_log must respect the caller's `action` param."""

    async def test_default_action_for_issue_comment(
        self, db_session: AsyncSession,
    ) -> None:
        """Without explicit action, the activity is logged as 'issue.commented'."""
        user, entry = await _seed_user_and_entry(db_session)

        service = EntityService(db_session)
        # Pre-register an "issue" entity that the comment will hang under.
        await service.register_forgejo_entity_and_log(
            entity_type="issue",
            parent_id=entry.id,
            external_ref="issues/1",
            created_by=user.id,
            action="issue.created",
        )
        await db_session.flush()

        await service.register_comment_and_log(
            parent_id=entry.id,
            issue_external_ref="issues/1",
            created_by=user.id,
        )
        await db_session.flush()

        # Pull every activity for the comment entity.
        activities = await db_session.execute(
            select(Activity).where(Activity.action == "issue.commented"),
        )
        rows = list(activities.scalars().all())
        assert len(rows) == 1
        assert rows[0].action == "issue.commented"
        assert rows[0].actor_id == user.id

    async def test_explicit_edit_commented_action_is_respected(
        self, db_session: AsyncSession,
    ) -> None:
        """When called with action='edit.commented', the activity row uses that exact action.

        Regression test: previously the action was hardcoded to
        'issue.commented' regardless of caller, so edit-proposal comments
        were mis-tagged in the activity feed.
        """
        user, entry = await _seed_user_and_entry(db_session)

        service = EntityService(db_session)
        # Pre-register an "edit" parent entity.
        await service.register_forgejo_entity_and_log(
            entity_type="edit",
            parent_id=entry.id,
            external_ref="pulls/2",
            created_by=user.id,
            action="edit.created",
        )
        await db_session.flush()

        await service.register_comment_and_log(
            parent_id=entry.id,
            issue_external_ref="pulls/2",
            created_by=user.id,
            action="edit.commented",
        )
        await db_session.flush()

        activities = await db_session.execute(
            select(Activity).where(Activity.action == "edit.commented"),
        )
        rows = list(activities.scalars().all())
        assert len(rows) == 1
        assert rows[0].action == "edit.commented"
        assert rows[0].actor_id == user.id

        # And NO 'issue.commented' row was created — the action is not
        # being silently appended in addition to the explicit one.
        wrong = await db_session.execute(
            select(Activity).where(Activity.action == "issue.commented"),
        )
        assert wrong.scalars().first() is None

    async def test_missing_parent_entity_returns_none(
        self, db_session: AsyncSession,
    ) -> None:
        """If the parent entity isn't registered, returns None and does not log."""
        user, entry = await _seed_user_and_entry(db_session)

        service = EntityService(db_session)
        result = await service.register_comment_and_log(
            parent_id=entry.id,
            issue_external_ref="issues/999",  # never registered
            created_by=user.id,
            action="edit.commented",
        )
        assert result is None

        activities = await db_session.execute(
            select(Activity).where(Activity.action == "edit.commented"),
        )
        assert activities.scalars().first() is None
