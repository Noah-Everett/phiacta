# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Entry service — business logic for entry operations.

This is the first service in the codebase. It sits between the API route
handlers and the repositories/models, owning transactional boundaries and
orchestrating writes to multiple tables (e.g. Entry + Outbox atomically).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.models.agent import Agent
from phiacta.models.entry import Entry
from phiacta.models.outbox import Outbox
from phiacta.schemas.entry import EntryCreate


class EntryService:
    """Business logic for entry lifecycle operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_entry(self, body: EntryCreate, agent: Agent) -> Entry:
        """Create an entry and enqueue its Forgejo repo provisioning.

        Creates both the Entry row and the Outbox row in a single
        transaction. The outbox worker will pick up the task and
        provision the git repository on Forgejo.

        Returns the created Entry (with repo_status='provisioning').
        """
        entry = Entry(
            title=body.title,
            content_format=body.content_format,
            layout_hint=body.layout_hint,
            tags=body.tags,
            summary=body.summary,
            license=body.license,
            created_by=agent.id,
            # repo_name must be the entry UUID — matches ForgejoGitService
            # and the webhook handler's repo name → entry_id lookup.
            repo_name="placeholder",  # set after flush gives us the id
        )
        self._session.add(entry)
        await self._session.flush()

        # Now entry.id is populated
        entry.repo_name = str(entry.id)

        # Build the outbox payload with ALL fields needed for provisioning
        outbox_entry = Outbox(
            aggregate_id=entry.id,
            aggregate_type="entry",
            operation="create_repo",
            payload={
                "entry_id": str(entry.id),
                "title": body.title,
                "content_format": body.content_format,
                "author_id": str(agent.id),
                "author_handle": agent.handle,
                "tags": body.tags,
                "summary": body.summary,
                "license": body.license,
                "layout_hint": body.layout_hint,
                "content": body.content,
                "created_at": entry.created_at.isoformat(),
            },
        )
        self._session.add(outbox_entry)

        await self._session.commit()
        await self._session.refresh(entry)
        return entry
