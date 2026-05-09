# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Entity service — business logic for entity registration and activity logging.

Provides helpers that API handlers call to register entities in the universal
registry and log activity events. All operations happen within the caller's
DB session/transaction.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.activity import Activity
from phiacta.core.models.entity import Entity
from phiacta.core.repositories.activity_repository import ActivityRepository
from phiacta.core.repositories.entity_repository import EntityRepository

logger = logging.getLogger(__name__)


class EntityService:
    """Business logic for entity registration and activity logging."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._entity_repo = EntityRepository(session)
        self._activity_repo = ActivityRepository(session)

    async def register_entity(
        self,
        *,
        entity_type: str,
        parent_id: UUID | None = None,
        external_ref: str | None = None,
        created_by: UUID | None = None,
        id: UUID | None = None,
    ) -> Entity:
        """Register an entity in the universal registry.

        For entries and users, pass ``id`` to use the shared-PK strategy.
        For Forgejo-backed objects (issues, edits, comments), omit ``id``
        to generate a fresh UUID.
        """
        return await self._entity_repo.create(
            entity_type=entity_type,
            parent_id=parent_id,
            external_ref=external_ref,
            created_by=created_by,
            id=id,
        )

    async def log_activity(
        self,
        *,
        actor_id: UUID,
        action: str,
        entity_id: UUID,
        metadata: dict | None = None,
    ) -> Activity:
        """Log an activity event in the append-only activity table."""
        return await self._activity_repo.log(
            actor_id=actor_id,
            action=action,
            entity_id=entity_id,
            metadata=metadata,
        )

    async def get_entity_by_external_ref(
        self, parent_id: UUID, external_ref: str,
    ) -> Entity | None:
        """Look up a Forgejo-backed entity by its parent and external ref."""
        return await self._entity_repo.get_by_external_ref(
            parent_id, external_ref,
        )

    # ------------------------------------------------------------------
    # Higher-level methods for Forgejo-backed operations
    # ------------------------------------------------------------------

    async def register_forgejo_entity_and_log(
        self,
        *,
        entity_type: str,
        parent_id: UUID,
        external_ref: str,
        created_by: UUID,
        action: str,
        metadata: dict | None = None,
    ) -> Entity:
        """Register a Forgejo-backed entity and log activity atomically.

        Call AFTER a successful Forgejo operation. Creates the entity row,
        logs the activity event, and flushes (caller must commit).
        """
        entity = await self.register_entity(
            entity_type=entity_type,
            parent_id=parent_id,
            external_ref=external_ref,
            created_by=created_by,
        )
        await self.log_activity(
            actor_id=created_by,
            action=action,
            entity_id=entity.id,
            metadata=metadata,
        )
        return entity

    async def log_activity_for_external_ref(
        self,
        *,
        parent_id: UUID,
        external_ref: str,
        actor_id: UUID,
        action: str,
        metadata: dict | None = None,
    ) -> None:
        """Log activity for an existing Forgejo-backed entity (close/merge).

        Looks up the entity by external_ref. If not found, logs a warning
        and skips silently (graceful degradation).
        """
        entity = await self.get_entity_by_external_ref(parent_id, external_ref)
        if entity is not None:
            await self.log_activity(
                actor_id=actor_id,
                action=action,
                entity_id=entity.id,
                metadata=metadata,
            )
        else:
            logger.warning(
                "Entity not found for %s on parent=%s, skipping activity log",
                external_ref, parent_id,
            )

    async def register_comment_and_log(
        self,
        *,
        parent_id: UUID,
        issue_external_ref: str,
        created_by: UUID,
        external_ref: str | None = None,
        metadata: dict | None = None,
        action: str = "issue.commented",
    ) -> Entity | None:
        """Register a comment entity under a parent entity and log activity.

        Despite the parameter name ``issue_external_ref`` (kept for
        backwards compatibility), the parent entity may be either an
        issue or an edit proposal. Callers commenting on an edit
        proposal should pass ``action="edit.commented"`` so the activity
        feed reflects the correct event type.

        Looks up the parent entity by external_ref. If not found, logs a
        warning and returns None (graceful degradation).
        """
        issue_entity = await self.get_entity_by_external_ref(
            parent_id, issue_external_ref,
        )
        if issue_entity is None:
            logger.warning(
                "Parent entity not found for %s on parent=%s, "
                "skipping comment entity registration",
                issue_external_ref, parent_id,
            )
            return None

        comment_entity = await self.register_entity(
            entity_type="comment",
            parent_id=issue_entity.id,
            external_ref=external_ref,
            created_by=created_by,
        )
        await self.log_activity(
            actor_id=created_by,
            action=action,
            entity_id=comment_entity.id,
            metadata=metadata,
        )
        return comment_entity
