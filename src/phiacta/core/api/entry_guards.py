# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Shared precondition checks and visibility guards for entry endpoints.

Provides guard functions for write endpoints (ownership, repo readiness)
and read endpoints (visibility).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.user import User
from phiacta.core.models.entry import Entry
from phiacta.core.repositories.entry_repository import EntryRepository
from phiacta.core.visibility import check_entry_access  # noqa: F401 — re-export


async def get_writable_entry(
    entry_id: UUID,
    user: User,
    db: AsyncSession,
) -> Entry:
    """Load an entry and verify it is writable by the given user.

    Raises HTTPException for missing entry (404), unready repo (409),
    or non-owner (403).  Entries are always editable by their owner.
    """
    repo = EntryRepository(db)
    entry = await repo.get_by_id(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    if entry.repo_status != "ready":
        raise HTTPException(
            status_code=409, detail="Entry repository is not yet ready",
        )
    if entry.created_by != user.id:
        raise HTTPException(
            status_code=403,
            detail="Only the entry author can modify files in this entry",
        )
    return entry


async def get_proposable_entry(
    entry_id: UUID,
    db: AsyncSession,
) -> Entry:
    """Load an entry and verify it can receive edit proposals.

    Checks that the entry exists (404) and repo is ready (409).
    Does NOT check ownership — any authenticated user can create a proposal.
    """
    repo = EntryRepository(db)
    entry = await repo.get_by_id(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    if entry.repo_status != "ready":
        raise HTTPException(
            status_code=409, detail="Entry repository is not yet ready",
        )
    return entry


async def get_readable_entry(
    entry_id: UUID,
    db: AsyncSession,
    user: User | None = None,
) -> Entry:
    """Load an entry and verify it is readable by the caller.

    Checks that the entry exists (404), visibility allows access (403),
    and repo is ready (409).
    """
    repo = EntryRepository(db)
    entry = await repo.get_by_id(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    check_entry_access(entry, user)
    if entry.repo_status != "ready":
        raise HTTPException(
            status_code=409, detail="Entry repository is not yet ready",
        )
    return entry


async def get_owned_entry(
    entry_id: UUID,
    user: User,
    db: AsyncSession,
) -> Entry:
    """Load an entry and verify the user is the owner.

    Like ``get_writable_entry`` but does NOT check repo_status.
    Used for operations where the entry may not be ready yet.

    Raises HTTPException for missing entry (404) or non-owner (403).
    """
    repo = EntryRepository(db)
    entry = await repo.get_by_id(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    if entry.created_by != user.id:
        raise HTTPException(
            status_code=403,
            detail="Only the entry author can perform this action",
        )
    return entry
