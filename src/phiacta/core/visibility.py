# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Canonical archive visibility filter for entry queries.

Provides the SQLAlchemy-level condition used by repositories and tools
to hide archived entries from non-owners.  Kept in its own module to
avoid circular imports between entry_guards (which imports
EntryRepository) and entry_repository (which needs this condition).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_

from phiacta.core.models.entry import Entry


def archive_visibility_condition(viewer_id: UUID | None):
    """Return a SQLAlchemy filter that hides archived entries from non-owners.

    Use in list/search queries so archived entries only appear for their
    creator.  When ``viewer_id`` is None (unauthenticated), all archived
    entries are excluded.
    """
    if viewer_id is None:
        return Entry.status != "archived"
    return or_(Entry.status != "archived", Entry.created_by == viewer_id)
