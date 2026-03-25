# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Entry service — business logic for entry operations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.user import User
from phiacta.core.models.entry import Entry
from phiacta.core.models.outbox import Outbox
from phiacta.core.schemas.entry import EntryCreate
from phiacta.core.services.entity_service import EntityService
from phiacta.core.services.git_service import GitService
from phiacta.extensions.metadata.service import MetadataService
from phiacta.extensions.types.service import TypeService


class EntryService:
    def __init__(self, session: AsyncSession, git_service: GitService | None = None) -> None:
        self._session = session
        self._git = git_service
        self._entity_service = EntityService(session)
        self._metadata_service = MetadataService(session)
        self._type_service = TypeService(session)

    async def create_entry(self, body: EntryCreate, user: User) -> Entry:
        entity = await self._entity_service.register_entity(
            entity_type="entry", created_by=user.id,
        )
        entry = Entry(id=entity.id, created_by=user.id, repo_name=str(entity.id))
        self._session.add(entry)
        await self._session.flush()

        await self._metadata_service.create_for_entry(
            entry_id=entry.id, title=body.title, user_id=user.id, summary=body.summary,
        )
        if body.entry_type is not None:
            await self._type_service.create_for_entry(
                entry_id=entry.id, entry_type=body.entry_type, user_id=user.id,
            )

        outbox_entry = Outbox(
            aggregate_id=entry.id, aggregate_type="entry", operation="create_repo",
            payload={
                "entry_id": str(entry.id),
                "title": body.title,
                "content_format": body.content_format,
                "author_id": str(user.id),
                "author_handle": user.handle,
                "content": body.content,
                "created_at": entry.created_at.isoformat(),
            },
        )
        self._session.add(outbox_entry)

        await self._entity_service.log_activity(
            actor_id=user.id, action="entry.created",
            entity_id=entry.id, metadata={"title": body.title},
        )

        await self._session.commit()
        await self._session.refresh(entry)
        return entry

    async def archive_entry(self, entry: Entry, user_id: UUID | None = None) -> Entry:
        if self._git is None:
            raise RuntimeError("GitService required for archival")
        if entry.status not in ("active", "draft"):
            raise ValueError(f"Cannot archive entry with status '{entry.status}'")
        entry.status = "archived"
        await self._git.archive_repo(entry.id)
        if user_id is not None:
            await self._entity_service.log_activity(
                actor_id=user_id, action="entry.archived", entity_id=entry.id,
            )
        await self._session.commit()
        await self._session.refresh(entry)
        return entry

    async def unarchive_entry(self, entry: Entry, user_id: UUID | None = None) -> Entry:
        if self._git is None:
            raise RuntimeError("GitService required for unarchival")
        if entry.status != "archived":
            raise ValueError(f"Cannot unarchive entry with status '{entry.status}'")
        await self._git.unarchive_repo(entry.id)
        entry.status = "active"
        if user_id is not None:
            await self._entity_service.log_activity(
                actor_id=user_id, action="entry.unarchived", entity_id=entry.id,
            )
        await self._session.commit()
        await self._session.refresh(entry)
        return entry
