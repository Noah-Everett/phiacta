# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Entry service — business logic for entry operations.

This is the first service in the codebase. It sits between the API route
handlers and the repositories/models, owning transactional boundaries and
orchestrating writes to multiple tables (e.g. Entry + Outbox atomically).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.agent import Agent
from phiacta.core.models.entry import Entry
from phiacta.core.models.outbox import Outbox
from phiacta.core.schemas.entry import EntryCreate, EntryUpdate
from phiacta.core.services.entry_yaml import update_entry_yaml
from phiacta.core.services.git_service import AgentInfo, FileContent, GitService


class EntryService:
    """Business logic for entry lifecycle operations."""

    def __init__(
        self, session: AsyncSession, git_service: GitService | None = None,
    ) -> None:
        self._session = session
        self._git = git_service

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

    async def update_entry_metadata(
        self, entry: Entry, body: EntryUpdate, agent: Agent,
    ) -> str:
        """Update entry metadata via a git-first write.

        Reads the current ``.phiacta/entry.yaml`` from git, merges the
        requested field updates, and commits the new YAML. The DB is
        updated asynchronously by the webhook ingestion pipeline.

        Returns the new commit SHA.
        """
        assert self._git is not None, "GitService required for metadata updates"

        # Collect only the fields that were actually provided
        updates = body.model_dump(exclude_unset=True)
        if not updates:
            return ""

        # Read current entry.yaml from git
        raw = await self._git.read_file(entry.id, ".phiacta/entry.yaml")
        existing_yaml = raw.decode()

        # Merge updates and produce new YAML
        new_yaml = update_entry_yaml(existing_yaml, updates)

        # Commit updated entry.yaml
        changed_fields = ", ".join(updates.keys())
        message = f"Update metadata: {changed_fields}"
        author = AgentInfo(
            name=agent.handle, email=f"{agent.id}@phiacta.local",
        )
        sha = await self._git.commit_files(
            entry.id,
            [FileContent(path=".phiacta/entry.yaml", content=new_yaml.encode())],
            author,
            message,
        )
        return sha

    async def archive_entry(self, entry: Entry) -> Entry:
        """Archive an entry — set DB status and make Forgejo repo read-only.

        Raises ``ValueError`` if the entry is not in an archivable state.
        """
        assert self._git is not None, "GitService required for archival"

        if entry.status not in ("active", "draft"):
            raise ValueError(
                f"Cannot archive entry with status '{entry.status}'"
            )

        entry.status = "archived"
        await self._git.archive_repo(entry.id)
        await self._session.commit()
        await self._session.refresh(entry)
        return entry

    async def unarchive_entry(self, entry: Entry) -> Entry:
        """Unarchive an entry — restore to active and unarchive Forgejo repo.

        Unarchives Forgejo first so that if the DB update fails, the repo
        stays archived (safe state). Raises ``ValueError`` if not archived.
        """
        assert self._git is not None, "GitService required for unarchival"

        if entry.status != "archived":
            raise ValueError(
                f"Cannot unarchive entry with status '{entry.status}'"
            )

        # Unarchive Forgejo FIRST — if this fails, DB stays archived (safe)
        await self._git.unarchive_repo(entry.id)
        entry.status = "active"
        await self._session.commit()
        await self._session.refresh(entry)
        return entry
