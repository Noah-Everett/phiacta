# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Shared ingestion logic — identity validation + search indexing."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.entry import Entry
from phiacta.core.services.entry_yaml import parse_entry_yaml
from phiacta.core.services.git_service import GitService, RepoNotFoundError
from phiacta.views.search_tsv.compute import compute_search_tsv

logger = logging.getLogger(__name__)

_CONTENT_EXTENSIONS = [".md", ".tex", ".txt"]


async def _read_content_file(
    entry_id: UUID, git_service: GitService, ref: str,
) -> str | None:
    for ext in _CONTENT_EXTENSIONS:
        path = f".phiacta/content{ext}"
        try:
            content_bytes = await git_service.read_file(entry_id, path, ref=ref)
            return content_bytes.decode("utf-8")
        except RepoNotFoundError:
            continue
        except UnicodeDecodeError:
            logger.warning("Content file %s for entry %s is not valid UTF-8", path, entry_id)
            continue
    return None


async def ingest_entry(
    entry: Entry, sha: str, db: AsyncSession, git_service: GitService,
) -> None:
    entry_id = entry.id

    yaml_bytes = await git_service.read_file(entry_id, ".phiacta/entry.yaml", ref=sha)
    try:
        yaml_str = yaml_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"entry.yaml for entry {entry_id} is not valid UTF-8") from exc
    parsed = parse_entry_yaml(yaml_str)

    yaml_entry_id = parsed.get("entry_id")
    if yaml_entry_id != entry_id:
        raise ValueError(f"entry_id mismatch for entry {entry_id}: YAML has {yaml_entry_id}")

    schema_version = parsed.get("schema_version")
    if isinstance(schema_version, int):
        entry.schema_version = schema_version
    await db.flush()

    content = await _read_content_file(entry_id, git_service, ref=sha)

    from phiacta.extensions.metadata.repository import MetadataRepository
    meta_repo = MetadataRepository(db)
    meta = await meta_repo.get_by_entry_id(entry_id)
    title = meta.title if meta else None

    searchable_parts: list[str] = []
    if title:
        searchable_parts.append(title)
    if content:
        searchable_parts.append(content)
    searchable_text = "\n\n".join(searchable_parts) if searchable_parts else None

    await compute_search_tsv(entry_id=entry_id, content_cache=searchable_text, version_id=None, db=db)
