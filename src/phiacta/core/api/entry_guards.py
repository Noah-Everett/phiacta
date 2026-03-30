# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Shared precondition checks for entry write endpoints.

Extracted from ``entry_files.py`` so that both file-write and metadata-update
endpoints reuse the same ownership and status checks.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.user import User
from phiacta.core.models.entry import Entry
from phiacta.core.repositories.entry_repository import EntryRepository

# Statuses that allow modifications (file writes, metadata updates).
EDITABLE_STATUSES = ("active", "draft")


def check_archive_visibility(entry: Entry, user: User | None) -> None:
    """Raise 404 if the entry is archived and the user is not the owner.

    Archived entries are only visible to their creator.  For everyone
    else they behave as if they don't exist.
    """
    if entry.status == "archived" and (user is None or entry.created_by != user.id):
        raise HTTPException(status_code=404, detail="Entry not found")


def archive_visibility_condition(viewer_id: UUID | None):
    """Return a SQLAlchemy filter that hides archived entries from non-owners.

    Use in list/search queries so archived entries only appear for their
    creator.  When ``viewer_id`` is None (unauthenticated), all archived
    entries are excluded.
    """
    if viewer_id is None:
        return Entry.status != "archived"
    return or_(Entry.status != "archived", Entry.created_by == viewer_id)


async def get_writable_entry(
    entry_id: UUID,
    user: User,
    db: AsyncSession,
) -> Entry:
    """Load an entry and verify it is writable by the given user.

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

    Checks that the entry exists (404), repo is ready (409), and status
    is editable (403).  Does NOT check ownership — any authenticated
    user can create a proposal.
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
    return entry


async def get_readable_entry(
    entry_id: UUID,
    db: AsyncSession,
    user: User | None = None,
) -> Entry:
    """Load an entry and verify its repo is ready for read operations.

    Checks that the entry exists (404), repo is ready (409), and the
    entry is visible to the caller (archived entries are owner-only).
    Does NOT check ownership or editable status — used for public
    read endpoints like listing proposals on any entry.
    """
    repo = EntryRepository(db)
    entry = await repo.get_by_id(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    check_archive_visibility(entry, user)
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

    Like ``get_writable_entry`` but does NOT check editable status or
    repo_status. Used for archival/unarchival where the entry may already
    be archived.

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
