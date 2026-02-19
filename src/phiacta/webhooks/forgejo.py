# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Forgejo webhook handler.

Handles push events from Forgejo to keep Postgres in sync with git state.
The webhook is registered on each claim repo by the outbox worker during
repo provisioning.

Verification uses HMAC-SHA256 over the request body, matching the shared
secret stored in ``FORGEJO_WEBHOOK_SECRET``.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.config import get_settings
from phiacta.db.session import get_db
from phiacta.extensions.dispatcher import dispatch_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_signature(body: bytes, signature: str, secret: str) -> bool:
    """Verify HMAC-SHA256 signature from Forgejo.

    Forgejo sends the signature in the ``X-Forgejo-Signature`` header
    as a hex-encoded HMAC-SHA256 digest.
    """
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
) -> dict[str, str]:
    """Handle incoming Forgejo webhook events.

    Currently handles:
    - ``push``: Updates claim ``current_head_sha`` and ``content_cache``.
    """
    settings = get_settings()

    # Read and verify signature
    body = await request.body()
    signature = request.headers.get("X-Forgejo-Signature", "")
    if not _verify_signature(body, signature, settings.forgejo_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Parse event type
    event_type = request.headers.get("X-Forgejo-Event", "")
    payload = await request.json()

    if event_type == "push":
        await _handle_push(payload, db)
    else:
        logger.debug("Ignoring Forgejo event type: %s", event_type)

    return {"status": "ok"}


async def _handle_push(payload: dict, db: AsyncSession) -> None:
    """Handle a push event: update claim head SHA and content cache.

    The repo name is the claim UUID (set during repo creation).
    """
    repo = payload.get("repository", {})
    repo_name = repo.get("name", "")

    # Validate that repo_name is a valid UUID (it should be the claim_id)
    try:
        claim_id = UUID(repo_name)
    except ValueError:
        logger.warning("Push event for non-claim repo: %s", repo_name)
        return

    # Extract the new head SHA
    after_sha = payload.get("after", "")
    if not after_sha or after_sha == "0" * 40:
        # Branch deletion — ignore
        return

    ref = payload.get("ref", "")
    if ref != "refs/heads/main":
        # Only track main branch pushes for content sync
        logger.debug("Ignoring push to non-main ref: %s", ref)
        return

    # Update the claim's head SHA
    await db.execute(
        text("""
            UPDATE claims SET current_head_sha = :sha
            WHERE id = :claim_id
        """),
        {"sha": after_sha, "claim_id": claim_id},
    )

    # Try to extract content from the push payload's commits
    # (Forgejo includes modified file content in some webhook configurations)
    commits = payload.get("commits", [])
    if commits:
        last_commit = commits[-1]
        message = last_commit.get("message", "")
        logger.info(
            "Push to claim %s: %s (sha=%s)",
            claim_id,
            message[:80],
            after_sha[:12],
        )

    await db.commit()

    # Dispatch event for extensions
    await dispatch_event(
        db,
        "claim.content_updated",
        {
            "claim_id": str(claim_id),
            "head_sha": after_sha,
            "ref": ref,
        },
    )
