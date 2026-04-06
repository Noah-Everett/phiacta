# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""search_tsv compute function — idempotent tsvector computation.

Called by the outbox worker when a compute_views task is processed.
Handles three cases:
- content is None/empty/whitespace → delete existing tsvector row
- version_id is None → look up active version; no-op if none found
- valid content + version → upsert tsvector via repository
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.extensions.search_tsv.repository import (
    delete_by_entry,
    get_active_version,
    upsert,
)

logger = logging.getLogger(__name__)

_DEFAULT_LANGUAGE = "english"


async def compute_search_tsv(
    *,
    entry_id: UUID,
    content_cache: str | None,
    version_id: UUID | None,
    db: AsyncSession,
) -> None:
    """Compute and store the tsvector for an entry.

    Idempotent: calling twice with the same content produces the same result.

    - NULL/empty/whitespace content_cache → delete existing tsvector row.
    - version_id=None → look up active version; log warning and no-op if none.
    - Valid content + version → upsert via repository (uses to_tsvector in SQL).

    Catches IntegrityError for entries deleted between task creation and
    processing (FK violation on entry_id).
    """
    if version_id is None:
        version = await get_active_version(db=db)
        if version is None:
            logger.warning(
                "No active ViewVersion for search_tsv — skipping computation "
                "for entry %s",
                entry_id,
            )
            return
        version_id = version.id
        language = version.parameters.get("language", _DEFAULT_LANGUAGE)
    else:
        language = _DEFAULT_LANGUAGE

    has_content = content_cache is not None and content_cache.strip()

    if not has_content:
        await delete_by_entry(entry_id=entry_id, version_id=version_id, db=db)
        logger.debug("Deleted search_tsv row for entry %s", entry_id)
        return

    try:
        await upsert(
            entry_id=entry_id,
            version_id=version_id,
            content=content_cache,
            language=language,
            db=db,
        )
        logger.debug(
            "Upserted search_tsv row for entry %s (version %s)",
            entry_id,
            version_id,
        )
    except IntegrityError:
        logger.warning(
            "IntegrityError computing search_tsv for entry %s — "
            "entry was likely deleted",
            entry_id,
        )
