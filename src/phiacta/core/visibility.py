# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Canonical visibility filters for entry queries.

Provides SQLAlchemy-level conditions and a guard function for enforcing
entry visibility based on the ``visibility`` column (public/private).

- ``access_condition`` — for direct access (GET by ID, sub-resources).
- ``discovery_condition`` — for listings, search, graph traversal.
- ``check_entry_access`` — guard that raises 403 for private entries.

Safe defaults: passing ``None`` means unauthenticated — only public
entries are visible.  Forgetting to pass the viewer means you see LESS,
not MORE.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_

from phiacta.core.models.entry import Entry

if TYPE_CHECKING:
    from phiacta.core.models.user import User


def _resolve_viewer_id(viewer: User | UUID | None) -> UUID | None:
    """Extract a UUID from a User object or pass through a UUID/None."""
    if viewer is None:
        return None
    if isinstance(viewer, UUID):
        return viewer
    return viewer.id


def access_condition(user: User | UUID | None = None):
    """SQLAlchemy filter for direct access (GET by ID, sub-resources).

    Public entries are visible to everyone.  Private entries are visible
    only to their creator.  Accepts a User object or a raw UUID.
    """
    viewer_id = _resolve_viewer_id(user)
    if viewer_id is None:
        return Entry.visibility == "public"
    return or_(Entry.visibility == "public", Entry.created_by == viewer_id)


def discovery_condition(user: User | UUID | None = None):
    """SQLAlchemy filter for listings, search, and graph traversal.

    Same logic as ``access_condition`` — public entries visible to all,
    private only to owner.  The behavioral difference is in the caller:
    direct access returns 403, discovery silently excludes.
    """
    viewer_id = _resolve_viewer_id(user)
    if viewer_id is None:
        return Entry.visibility == "public"
    return or_(Entry.visibility == "public", Entry.created_by == viewer_id)


def check_entry_access(entry: Entry, user: User | None) -> None:
    """Raise 403 if the entry is private and the user is not the owner.

    Used for direct-access endpoints (GET /entries/{id}, sub-resources,
    entity resolve).  For listings/search/graph, use ``discovery_condition``
    instead — those silently exclude private entries.
    """
    if entry.visibility == "private":
        if user is None or entry.created_by != user.id:
            raise HTTPException(
                status_code=403,
                detail="You do not have access to this entry",
            )
