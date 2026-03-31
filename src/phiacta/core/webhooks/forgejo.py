# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Forgejo webhook handler.

Handles push events from Forgejo to keep Postgres in sync with git state.
The webhook is registered on each entry repo by the outbox worker during
repo provisioning.

Verification uses HMAC-SHA256 over the request body, matching the shared
secret stored in ``FORGEJO_WEBHOOK_SECRET``.

After verifying the push, the handler runs ingestion: fetches
``.phiacta/content.*`` from the new HEAD and runs on_ingest hooks
(extensions, views) to keep derived data in sync.
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
from phiacta.core.db.session import get_db
from phiacta.core.repositories.entry_repository import EntryRepository
from phiacta.core.services.git_service import GitService
from phiacta.core.services.git_service_dep import get_git_service
from phiacta.core.services.ingestion import ingest_entry

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


def _get_on_ingest_hooks(request: Request) -> list:
    """Read on_ingest hooks from the plugin registry."""
    registry = getattr(request.app.state, "plugin_registry", None)
    if registry is not None:
        return registry.get_on_ingest_hooks()
    return getattr(request.app.state, "on_ingest_hooks", [])


@router.post("/forgejo")
async def handle_forgejo_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    git_service: GitService = Depends(get_git_service),
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
        try:
            payload = await request.json()
        except (ValueError, KeyError):
            raise HTTPException(status_code=400, detail="Malformed JSON payload")
        hooks = _get_on_ingest_hooks(request)
        await _handle_push(payload, db, git_service, hooks)
    else:
        logger.debug("Ignoring Forgejo event type: %s", event_type)

    return {"status": "ok"}


async def _handle_push(
    payload: dict, db: AsyncSession, git_service: GitService, hooks: list,
) -> None:
    """Handle a push event: update entry head SHA and run ingestion.

    The repo name is the entry UUID (set during repo creation).
    Ingestion errors are caught and logged; validation failures
    (unknown repo, bad SHA) return early without error.
    """
    repo_data = payload.get("repository", {})
    repo_name = repo_data.get("name", "")

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

    # Load entry
    entry_repo = EntryRepository(db)
    entry = await entry_repo.get_by_id(entry_id)
    if entry is None:
        logger.warning("Push event for unknown entry: %s", entry_id)
        return

    # Idempotency check: skip ingestion if SHA hasn't changed
    already_ingested = entry.current_head_sha == after_sha

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

    if already_ingested:
        logger.debug("SHA %s already ingested for entry %s, skipping", after_sha[:12], entry_id)
        return

    # Run ingestion — wrapped in try/except to always return 200.
    # Update current_head_sha only AFTER successful ingestion so that
    # a transient failure will be retried on the next push.
    try:
        await ingest_entry(entry, after_sha, db, git_service, on_ingest_hooks=hooks)
        entry.current_head_sha = after_sha
    except Exception:
        logger.exception("Ingestion failed for entry %s at SHA %s", entry_id, after_sha[:12])

    await db.commit()
