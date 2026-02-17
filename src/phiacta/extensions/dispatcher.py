# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Fire-and-forget event dispatcher for notifying subscribed extensions."""

from __future__ import annotations

import asyncio
import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.config import get_settings
from phiacta.repositories.extension_repository import ExtensionRepository

logger = logging.getLogger(__name__)


# Limit concurrent outgoing notifications to prevent DoS amplification.
_DISPATCH_SEMAPHORE = asyncio.Semaphore(10)

# Maximum number of extensions to notify per event to bound amplification.
_MAX_EXTENSIONS_PER_EVENT = 50


async def _notify_extension(base_url: str, event_type: str, payload: dict) -> None:
    """Send an event notification to a single extension. Logs errors, never raises."""
    async with _DISPATCH_SEMAPHORE:
        try:
            settings = get_settings()
            async with httpx.AsyncClient(
                timeout=settings.extension_dispatch_timeout,
                follow_redirects=False,
                max_redirects=0,
            ) as client:
                resp = await client.post(
                    f"{base_url}/events",
                    json={"event_type": event_type, **payload},
                )
                if resp.status_code >= 400:
                    logger.warning(
                        "Extension at %s returned %s for event %s",
                        base_url,
                        resp.status_code,
                        event_type,
                    )
        except Exception:
            logger.exception(
                "Failed to notify extension at %s for event %s", base_url, event_type
            )


async def dispatch_event(
    session: AsyncSession,
    event_type: str,
    payload: dict,
    *,
    source_extension_id: str | None = None,
) -> None:
    """Fan out an event to all subscribed extensions (fire-and-forget).

    This creates background tasks that run independently -- the caller
    does not need to await their completion.

    Args:
        session: Database session to query registered extensions.
        event_type: Event type string (e.g. "claim.created").
        payload: Data to include in the notification (e.g. claim_ids).
        source_extension_id: If the event was caused by an extension,
            that extension will be excluded from notifications to prevent
            circular event loops.
    """
    repo = ExtensionRepository(session)
    extensions = await repo.list_by_event(event_type)

    if not extensions:
        return

    # Exclude the extension that caused this event to prevent infinite loops
    if source_extension_id:
        extensions = [e for e in extensions if str(e.id) != source_extension_id]

    if not extensions:
        return

    # Cap the number of extensions to prevent amplification attacks
    if len(extensions) > _MAX_EXTENSIONS_PER_EVENT:
        logger.warning(
            "Too many extensions (%d) subscribed to %s, capping at %d",
            len(extensions),
            event_type,
            _MAX_EXTENSIONS_PER_EVENT,
        )
        extensions = extensions[:_MAX_EXTENSIONS_PER_EVENT]

    logger.info("Dispatching %s to %d extension(s)", event_type, len(extensions))

    for ext in extensions:
        asyncio.create_task(
            _notify_extension(ext.base_url, event_type, payload),
            name=f"notify-{ext.name}-{event_type}",
        )
