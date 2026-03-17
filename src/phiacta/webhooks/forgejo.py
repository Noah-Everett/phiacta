# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Forgejo webhook handler.

Handles push events from Forgejo to keep Postgres in sync with git state.
The webhook is registered on each entry repo by the outbox worker during
repo provisioning.

Verification uses HMAC-SHA256 over the request body, matching the shared
secret stored in ``FORGEJO_WEBHOOK_SECRET``.

After verifying the push, the handler runs ingestion: fetches
``.phiacta/entry.yaml``, the README file, and ``.phiacta/refs.yaml``
from the new HEAD and syncs the parsed content into Postgres.
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
from phiacta.formats import FORMAT_EXTENSIONS
from phiacta.models.entry import Entry
from phiacta.models.entry_ref import EntryRef
from phiacta.repositories.entry_ref_repository import EntryRefRepository
from phiacta.repositories.entry_repository import EntryRepository
from phiacta.services.entry_yaml import parse_entry_yaml
from phiacta.services.git_service import GitService, RepoNotFoundError
from phiacta.services.git_service_dep import get_git_service
from phiacta.services.refs_yaml import parse_refs_yaml

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
        payload = await request.json()
        await _handle_push(payload, db, git_service)
    else:
        logger.debug("Ignoring Forgejo event type: %s", event_type)

    return {"status": "ok"}


async def _handle_push(
    payload: dict, db: AsyncSession, git_service: GitService
) -> None:
    """Handle a push event: update entry head SHA and run ingestion.

    The repo name is the entry UUID (set during repo creation).
    Always returns normally — errors are logged, never raised.
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

    # Update the entry's head SHA
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

    if already_ingested:
        logger.debug("SHA %s already ingested for entry %s, skipping", after_sha[:12], entry_id)
        await db.commit()
        return

    # Run ingestion — wrapped in try/except to always return 200
    try:
        await _ingest_push(entry, after_sha, db, git_service)
    except Exception:
        logger.exception("Ingestion failed for entry %s at SHA %s", entry_id, after_sha[:12])

    await db.commit()


async def _ingest_push(
    entry: Entry, sha: str, db: AsyncSession, git_service: GitService
) -> None:
    """Fetch files from Forgejo and sync metadata, content, and refs to Postgres."""
    entry_id = entry.id

    # --- 1. Fetch and parse entry.yaml (required) ---
    try:
        yaml_bytes = await git_service.read_file(entry_id, ".phiacta/entry.yaml", ref=sha)
    except RepoNotFoundError:
        logger.error("entry.yaml missing for entry %s at SHA %s", entry_id, sha[:12])
        return

    try:
        yaml_str = yaml_bytes.decode("utf-8")
        parsed = parse_entry_yaml(yaml_str)
    except (ValueError, UnicodeDecodeError) as exc:
        logger.error("Failed to parse entry.yaml for entry %s: %s", entry_id, exc)
        return

    # Validate entry_id matches (strip ent_ prefix)
    yaml_entry_id = str(parsed.get("entry_id", ""))
    if yaml_entry_id.startswith("ent_"):
        yaml_entry_id = yaml_entry_id[4:]
    if yaml_entry_id != str(entry_id):
        logger.error(
            "entry_id mismatch for entry %s: YAML has %s",
            entry_id, parsed.get("entry_id"),
        )
        return

    # --- 2. Update entry metadata from entry.yaml ---
    _update_entry_metadata(entry, parsed)
    await db.flush()

    # --- 3. Fetch README for content_cache ---
    content_format = parsed.get("content_format", "markdown")
    ext = FORMAT_EXTENSIONS.get(content_format, ".md")
    readme_path = f"README{ext}"

    try:
        readme_bytes = await git_service.read_file(entry_id, readme_path, ref=sha)
        entry.content_cache = readme_bytes.decode("utf-8")
    except RepoNotFoundError:
        logger.debug("README not found for entry %s at path %s", entry_id, readme_path)
        entry.content_cache = None
    except UnicodeDecodeError:
        logger.warning("README for entry %s is not valid UTF-8", entry_id)
        entry.content_cache = None

    # --- 4. Fetch and parse refs.yaml (optional) ---
    await _ingest_refs(entry, sha, db, git_service)


def _update_entry_metadata(entry: Entry, parsed: dict) -> None:
    """Update entry metadata fields from parsed entry.yaml, with truncation."""
    title = parsed.get("title")
    if isinstance(title, str):
        entry.title = title[:500]

    content_format = parsed.get("content_format")
    if isinstance(content_format, str):
        entry.content_format = content_format[:20]

    tags = parsed.get("tags")
    if isinstance(tags, list):
        entry.tags = [str(t)[:200] for t in tags]

    summary = parsed.get("summary")
    if summary is not None:
        entry.summary = str(summary) if summary else None

    license_val = parsed.get("license")
    if license_val is not None:
        entry.license = str(license_val)[:50] if license_val else None

    layout_hint = parsed.get("layout_hint")
    if layout_hint is not None:
        entry.layout_hint = str(layout_hint)[:50] if layout_hint else None

    schema_version = parsed.get("schema_version")
    if isinstance(schema_version, int):
        entry.schema_version = schema_version


async def _ingest_refs(
    entry: Entry, sha: str, db: AsyncSession, git_service: GitService
) -> None:
    """Fetch refs.yaml from the repo and replace all outgoing entry_refs."""
    entry_id = entry.id
    ref_repo = EntryRefRepository(db)
    entry_repo = EntryRepository(db)

    try:
        refs_bytes = await git_service.read_file(entry_id, ".phiacta/refs.yaml", ref=sha)
    except RepoNotFoundError:
        # No refs.yaml — delete all existing outgoing refs (YAML is source of truth)
        await ref_repo.delete_outgoing(entry_id)
        return

    try:
        refs_str = refs_bytes.decode("utf-8")
        ref_descriptors = parse_refs_yaml(refs_str)
    except (ValueError, UnicodeDecodeError) as exc:
        # Malformed refs.yaml — leave existing refs unchanged
        logger.error("Failed to parse refs.yaml for entry %s: %s", entry_id, exc)
        return

    # Delete all existing outgoing refs (replace-all pattern)
    await ref_repo.delete_outgoing(entry_id)

    # Insert new refs, filtering invalid ones
    for ref_desc in ref_descriptors:
        try:
            to_entry_id = UUID(ref_desc["to_entry_id"])
        except (ValueError, KeyError):
            logger.warning("Invalid to_entry_id in refs.yaml for entry %s", entry_id)
            continue

        # Filter self-references (would violate CHECK constraint)
        if to_entry_id == entry_id:
            logger.warning("Self-reference in refs.yaml for entry %s, skipping", entry_id)
            continue

        # Verify target entry exists
        target = await entry_repo.get_by_id(to_entry_id)
        if target is None:
            logger.warning(
                "Ref target %s not found for entry %s, skipping", to_entry_id, entry_id
            )
            continue

        # Truncate rel to column max (String(50))
        rel = str(ref_desc.get("rel", ""))[:50]

        new_ref = EntryRef(
            from_entry_id=entry_id,
            to_entry_id=to_entry_id,
            rel=rel,
            version_sha=ref_desc.get("version_sha"),
            note=ref_desc.get("note"),
        )
        db.add(new_ref)

    await db.flush()
