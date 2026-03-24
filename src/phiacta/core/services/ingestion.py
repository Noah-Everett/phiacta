# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Shared ingestion logic for syncing git state to Postgres.

Extracted from webhooks/forgejo.py so both the webhook handler and the
reconciliation service can call the same code path.

``ingest_entry()`` fetches ``.phiacta/entry.yaml``, the README, and
``.phiacta/refs.yaml`` from a git repo and updates the corresponding
``Entry`` and ``EntryRef`` rows.  It does NOT update ``current_head_sha``
— that is the caller's responsibility after a successful ingest.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.formats import FORMAT_EXTENSIONS
from phiacta.core.models.entry import Entry
from phiacta.core.models.entry_ref import EntryRef
from phiacta.core.repositories.entry_ref_repository import EntryRefRepository
from phiacta.core.services.entry_yaml import parse_entry_yaml
from phiacta.core.services.git_service import GitService, RepoNotFoundError
from phiacta.core.services.refs_yaml import parse_refs_yaml

logger = logging.getLogger(__name__)


async def ingest_entry(
    entry: Entry,
    sha: str,
    db: AsyncSession,
    git_service: GitService,
) -> None:
    """Re-ingest an entry from git.  Updates metadata, content_cache, and refs.

    Does NOT update ``current_head_sha`` — caller is responsible for that
    after successful ingest.

    Raises on missing/malformed ``entry.yaml`` or ``entry_id`` mismatch
    so the caller can decide whether to update the SHA.
    """
    entry_id = entry.id

    # --- 1. Fetch and parse entry.yaml (required) ---
    yaml_bytes = await git_service.read_file(entry_id, ".phiacta/entry.yaml", ref=sha)

    try:
        yaml_str = yaml_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"entry.yaml for entry {entry_id} is not valid UTF-8"
        ) from exc
    parsed = parse_entry_yaml(yaml_str)

    # Validate entry_id matches (strip ent_ prefix)
    yaml_entry_id = str(parsed.get("entry_id", ""))
    if yaml_entry_id.startswith("ent_"):
        yaml_entry_id = yaml_entry_id[4:]
    if yaml_entry_id != str(entry_id):
        raise ValueError(
            f"entry_id mismatch for entry {entry_id}: YAML has {parsed.get('entry_id')}"
        )

    # --- 2. Update entry metadata from entry.yaml ---
    update_entry_metadata(entry, parsed)
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
    await ingest_refs(entry, sha, db, git_service)


def update_entry_metadata(entry: Entry, parsed: dict) -> None:
    """Update entry metadata fields from parsed entry.yaml, with truncation."""
    title = parsed.get("title")
    if isinstance(title, str):
        entry.title = title[:500]

    content_format = parsed.get("content_format")
    if isinstance(content_format, str):
        entry.content_format = content_format[:20]

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


async def ingest_refs(
    entry: Entry,
    sha: str,
    db: AsyncSession,
    git_service: GitService,
) -> None:
    """Fetch refs.yaml from the repo and replace all outgoing entry_refs."""
    entry_id = entry.id
    ref_repo = EntryRefRepository(db)

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

    # Parse all candidate target IDs upfront for batch validation
    candidate_ids: set[UUID] = set()
    for ref_desc in ref_descriptors:
        raw_target_id = str(ref_desc.get("target", {}).get("entry_id", ""))
        if raw_target_id.startswith("ent_"):
            raw_target_id = raw_target_id[4:]
        try:
            candidate_ids.add(UUID(raw_target_id))
        except (ValueError, KeyError):
            pass

    # Batch-verify which target entries exist (single query instead of N+1)
    existing_ids: set[UUID] = set()
    if candidate_ids:
        result = await db.execute(
            select(Entry.id).where(Entry.id.in_(candidate_ids))
        )
        existing_ids = set(result.scalars().all())

    # Delete all existing outgoing refs (replace-all pattern)
    await ref_repo.delete_outgoing(entry_id)

    # Insert new refs, filtering invalid and duplicate ones
    seen: set[tuple[UUID, str]] = set()
    for ref_desc in ref_descriptors:
        # Strip ent_ prefix from target entry_id
        raw_target_id = str(ref_desc.get("target", {}).get("entry_id", ""))
        if raw_target_id.startswith("ent_"):
            raw_target_id = raw_target_id[4:]
        try:
            to_entry_id = UUID(raw_target_id)
        except (ValueError, KeyError):
            logger.warning("Invalid to_entry_id in refs.yaml for entry %s", entry_id)
            continue

        # Filter self-references (would violate CHECK constraint)
        if to_entry_id == entry_id:
            logger.warning("Self-reference in refs.yaml for entry %s, skipping", entry_id)
            continue

        # Verify target entry exists (uses batch-fetched set)
        if to_entry_id not in existing_ids:
            logger.warning(
                "Ref target %s not found for entry %s, skipping", to_entry_id, entry_id
            )
            continue

        # Truncate rel to column max (String(50))
        rel = str(ref_desc.get("rel", ""))[:50]

        # Skip duplicates (same to_entry_id + rel) — unique constraint would reject them
        key = (to_entry_id, rel)
        if key in seen:
            logger.warning(
                "Duplicate ref (%s, %s) in refs.yaml for entry %s, skipping",
                to_entry_id, rel, entry_id,
            )
            continue
        seen.add(key)

        # Truncate version_sha to column max (String(40))
        raw_version_sha = ref_desc.get("version_sha")
        version_sha = str(raw_version_sha)[:40] if raw_version_sha else None

        new_ref = EntryRef(
            from_entry_id=entry_id,
            to_entry_id=to_entry_id,
            rel=rel,
            version_sha=version_sha,
            note=ref_desc.get("note"),
        )
        db.add(new_ref)

    await db.flush()
