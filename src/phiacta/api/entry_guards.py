# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Shared precondition checks for entry write endpoints.

Extracted from ``entry_files.py`` so that both file-write and metadata-update
endpoints reuse the same ownership and status checks.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.models.agent import Agent
from phiacta.models.entry import Entry
from phiacta.repositories.entry_repository import EntryRepository

# Statuses that allow modifications (file writes, metadata updates).
EDITABLE_STATUSES = ("active", "draft")


async def get_writable_entry(
    entry_id: UUID,
    agent: Agent,
    db: AsyncSession,
) -> Entry:
    """Load an entry and verify it is writable by the given agent.

    Raises HTTPException for missing entry (404), unready repo (409),
    non-editable status (403), or non-owner (403).
    """
    repo = EntryRepository(db)
    entry = await repo.get_by_id(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    if entry.repo_status != "ready":
        raise HTTPException(
            status_code=409, detail="Entry repository is not yet ready",
        )
    if entry.status not in EDITABLE_STATUSES:
        raise HTTPException(
            status_code=403, detail="Entry is not editable",
        )
    if entry.created_by != agent.id:
        raise HTTPException(
            status_code=403,
            detail="Only the entry author can modify files in this entry",
        )
    return entry


async def get_owned_entry(
    entry_id: UUID,
    agent: Agent,
    db: AsyncSession,
) -> Entry:
    """Load an entry and verify the agent is the owner.

    Like ``get_writable_entry`` but does NOT check editable status or
    repo_status. Used for archival/unarchival where the entry may already
    be archived.

    Raises HTTPException for missing entry (404) or non-owner (403).
    """
    repo = EntryRepository(db)
    entry = await repo.get_by_id(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    if entry.created_by != agent.id:
        raise HTTPException(
            status_code=403,
            detail="Only the entry author can perform this action",
        )
    return entry
