# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Entry service — business logic for entry operations.

This is the first service in the codebase. It sits between the API route
handlers and the repositories/models, owning transactional boundaries and
orchestrating writes to multiple tables (e.g. Entry + Outbox atomically).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.user import User
from phiacta.core.models.entry import Entry
from phiacta.core.models.outbox import Outbox
from phiacta.core.schemas.entry import EntryCreate, EntryUpdate
from phiacta.core.services.entity_service import EntityService
from phiacta.core.services.entry_yaml import update_entry_yaml
from phiacta.core.services.git_service import AuthorInfo, FileContent, GitService


class EntryService:
    """Business logic for entry lifecycle operations."""

    def __init__(
        self, session: AsyncSession, git_service: GitService | None = None,
    ) -> None:
        self._session = session
        self._git = git_service
        self._entity_service = EntityService(session)

    async def create_entry(self, body: EntryCreate, user: User) -> Entry:
        """Create an entry and enqueue its Forgejo repo provisioning.

        Creates an Entity row (shared PK), the Entry row, and the Outbox
        row in a single transaction. The outbox worker will pick up the
        task and provision the git repository on Forgejo.

        Returns the created Entry (with repo_status='provisioning').
        """
        # 1. Create Entity row first (shared-PK strategy)
        entity = await self._entity_service.register_entity(
            entity_type="entry",
            created_by=user.id,
        )

        # 2. Create Entry with the same ID as the entity
        entry = Entry(
            id=entity.id,
            title=body.title,
            content_format=body.content_format,
            layout_hint=body.layout_hint,
            summary=body.summary,
            license=body.license,
            created_by=user.id,
            repo_name=str(entity.id),
        )
        self._session.add(entry)
        await self._session.flush()

        # 3. Build the outbox payload
        outbox_entry = Outbox(
            aggregate_id=entry.id,
            aggregate_type="entry",
            operation="create_repo",
            payload={
                "entry_id": str(entry.id),
                "title": body.title,
                "content_format": body.content_format,
                "author_id": str(user.id),
                "author_handle": user.handle,
                "summary": body.summary,
                "license": body.license,
                "layout_hint": body.layout_hint,
                "content": body.content,
                "created_at": entry.created_at.isoformat(),
            },
        )
        self._session.add(outbox_entry)

        # 4. Log activity
        await self._entity_service.log_activity(
            actor_id=user.id,
            action="entry.created",
            entity_id=entry.id,
            metadata={"title": body.title},
        )

        await self._session.commit()
        await self._session.refresh(entry)
        return entry

    async def update_entry_metadata(
        self, entry: Entry, body: EntryUpdate, user: User,
    ) -> str:
        """Update entry metadata via a git-first write."""
        if self._git is None:
            raise RuntimeError("GitService required for metadata updates")

        updates = body.model_dump(exclude_unset=True)
        if not updates:
            return ""

        raw = await self._git.read_file(entry.id, ".phiacta/entry.yaml")
        existing_yaml = raw.decode()
        new_yaml = update_entry_yaml(existing_yaml, updates)

        changed_fields = ", ".join(updates.keys())
        message = f"Update metadata: {changed_fields}"
        author = AuthorInfo(
            name=user.handle, email=f"{user.id}@phiacta.local",
        )
        sha = await self._git.commit_files(
            entry.id,
            [FileContent(path=".phiacta/entry.yaml", content=new_yaml.encode())],
            author,
            message,
        )
        return sha

    async def archive_entry(
        self, entry: Entry, user_id: UUID | None = None,
    ) -> Entry:
        """Archive an entry — set DB status and make Forgejo repo read-only."""
        if self._git is None:
            raise RuntimeError("GitService required for archival")

        if entry.status not in ("active", "draft"):
            raise ValueError(
                f"Cannot archive entry with status '{entry.status}'"
            )

        entry.status = "archived"
        await self._git.archive_repo(entry.id)

        if user_id is not None:
            await self._entity_service.log_activity(
                actor_id=user_id,
                action="entry.archived",
                entity_id=entry.id,
            )

        await self._session.commit()
        await self._session.refresh(entry)
        return entry

    async def unarchive_entry(
        self, entry: Entry, user_id: UUID | None = None,
    ) -> Entry:
        """Unarchive an entry — restore to active and unarchive Forgejo repo."""
        if self._git is None:
            raise RuntimeError("GitService required for unarchival")

        if entry.status != "archived":
            raise ValueError(
                f"Cannot unarchive entry with status '{entry.status}'"
            )

        await self._git.unarchive_repo(entry.id)
        entry.status = "active"

        if user_id is not None:
            await self._entity_service.log_activity(
                actor_id=user_id,
                action="entry.unarchived",
                entity_id=entry.id,
            )

        await self._session.commit()
        await self._session.refresh(entry)
        return entry
