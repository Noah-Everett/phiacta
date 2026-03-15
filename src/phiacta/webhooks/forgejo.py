# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Forgejo webhook handler.

Handles push events from Forgejo to keep Postgres in sync with git state.
The webhook is registered on each entry repo by the outbox worker during
repo provisioning.

Verification uses HMAC-SHA256 over the request body, matching the shared
secret stored in ``FORGEJO_WEBHOOK_SECRET``.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.config import Settings, get_settings
from phiacta.db.session import get_db
from phiacta.repositories.entry_repository import EntryRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _verify_signature(body: bytes, signature: str, secret: str) -> bool:
    """Verify HMAC-SHA256 signature from Forgejo."""
    if not secret:
        logger.warning("FORGEJO_WEBHOOK_SECRET is not configured — rejecting webhook")
        return False
    expected = hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/forgejo")
async def handle_forgejo_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Handle incoming Forgejo webhook events.

    Currently handles:
    - ``push``: Updates entry ``current_head_sha`` and runs ingestion.
    """

    # Read and verify signature
    body = await request.body()
    signature = request.headers.get("X-Forgejo-Signature", "")
    if not _verify_signature(body, signature, settings.forgejo_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Parse event type
    event_type = request.headers.get("X-Forgejo-Event", "")

    if event_type == "push":
        payload = await request.json()
        await _handle_push(payload, db)
    else:
        logger.debug("Ignoring Forgejo event type: %s", event_type)

    return {"status": "ok"}


async def _handle_push(payload: dict, db: AsyncSession) -> None:
    """Handle a push event: update entry head SHA.

    The repo name is the entry UUID (set during repo creation).
    """
    repo = payload.get("repository", {})
    repo_name = repo.get("name", "")

    # Validate that repo_name is a valid UUID (it should be the entry_id)
    try:
        entry_id = UUID(repo_name)
    except ValueError:
        logger.warning("Push event for non-entry repo: %s", repo_name)
        return

    # Extract the new head SHA
    after_sha = payload.get("after", "")
    if not after_sha or after_sha == "0" * 40:
        # Branch deletion — ignore
        return

    # Validate SHA format (40-char lowercase hex) to prevent DB errors
    if not _SHA_RE.match(after_sha):
        logger.warning("Push event with invalid SHA format: %s", after_sha[:50])
        return

    ref = payload.get("ref", "")
    if ref != "refs/heads/main":
        # Only track main branch pushes for content sync
        logger.debug("Ignoring push to non-main ref: %s", ref)
        return

    # Update the entry's head SHA via repository (preserves ORM onupdate)
    repo = EntryRepository(db)
    entry = await repo.get_by_id(entry_id)
    if entry is None:
        logger.warning("Push event for unknown entry: %s", entry_id)
        return
    entry.current_head_sha = after_sha
    await db.flush()

    # Log push info
    commits = payload.get("commits", [])
    if commits:
        last_commit = commits[-1]
        message = last_commit.get("message", "")
        logger.info(
            "Push to entry %s: %s (sha=%s)",
            entry_id,
            message[:80],
            after_sha[:12],
        )

    await db.commit()
