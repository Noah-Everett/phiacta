# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Entry service — business logic for entry operations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.compose import EntryDataProvider
from phiacta.core.models.user import User
from phiacta.core.models.entry import Entry
from phiacta.core.models.outbox import Outbox
from phiacta.core.schemas.entry import EntryCreate
from phiacta.core.services.entity_service import EntityService
from phiacta.core.services.git_service import GitService


class EntryService:
    def __init__(self, session: AsyncSession, git_service: GitService | None = None) -> None:
        self._session = session
        self._git = git_service
        self._entity_service = EntityService(session)

    async def create_entry(
        self,
        body: EntryCreate,
        user: User,
        *,
        providers: list[EntryDataProvider] | None = None,
        provider_fields: dict | None = None,
    ) -> Entry:
        providers = providers or []
        provider_fields = provider_fields or {}

        # Validate required_on_create before any DB work.
        missing: list[str] = []
        for provider in providers:
            for field in provider.required_on_create:
                if field not in provider_fields or provider_fields[field] is None:
                    missing.append(field)
        if missing:
            raise ValueError(
                f"Missing required fields: {', '.join(sorted(missing))}"
            )

        entity = await self._entity_service.register_entity(
            entity_type="entry", created_by=user.id,
        )
        entry = Entry(id=entity.id, created_by=user.id, repo_name=str(entity.id))
        self._session.add(entry)
        await self._session.flush()

        # Generic provider dispatch — route extra fields to owning providers.
        for provider in providers:
            if not provider.writable_fields:
                continue
            pdata = {
                k: v for k, v in provider_fields.items()
                if k in provider.writable_fields
            }
            if pdata:
                await provider.write(entry.id, pdata, user.id, self._session)

        outbox_entry = Outbox(
            aggregate_id=entry.id, aggregate_type="entry", operation="create_repo",
            payload={
                "entry_id": str(entry.id),
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
            entity_id=entry.id, metadata={},
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
