# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Docs endpoint — serves convention and guide documents for MCP discovery.

Reads markdown files from ``src/phiacta/docs/`` at startup. Each file has
YAML frontmatter (name, slug, description) and a markdown body. The MCP
server fetches these and registers them as MCP resources, making them
discoverable by agents.

To add a new doc: drop a ``.md`` file in ``src/phiacta/docs/`` with the
standard frontmatter. No code changes needed — restart picks it up.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/docs", tags=["docs"])

_DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "docs"


class DocResponse(BaseModel):
    """Single documentation resource with frontmatter metadata and markdown content."""

    name: str
    slug: str
    description: str
    content: str


def _load_docs() -> list[DocResponse]:
    """Read all markdown files from the docs directory.

    Called once at module load time. Results are cached for the lifetime
    of the process — new docs require a restart.
    """
    docs: list[DocResponse] = []
    if not _DOCS_DIR.is_dir():
        logger.warning("Docs directory not found: %s", _DOCS_DIR)
        return docs

    for md_file in sorted(_DOCS_DIR.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        if not text.startswith("---"):
            logger.warning("Skipping %s: no YAML frontmatter", md_file.name)
            continue

        # Split frontmatter from body
        parts = text.split("---", 2)
        if len(parts) < 3:
            logger.warning("Skipping %s: malformed frontmatter", md_file.name)
            continue

        try:
            meta = yaml.safe_load(parts[1])
        except yaml.YAMLError as exc:
            logger.warning("Skipping %s: YAML parse error: %s", md_file.name, exc)
            continue

        if not isinstance(meta, dict):
            logger.warning("Skipping %s: frontmatter is not a mapping", md_file.name)
            continue

        name = meta.get("name", md_file.stem)
        slug = meta.get("slug", md_file.stem)
        description = meta.get("description", "")
        content = parts[2].strip()

        docs.append(
            DocResponse(
                name=name,
                slug=slug,
                description=description,
                content=content,
            )
        )

    logger.info("Loaded %d docs from %s", len(docs), _DOCS_DIR)
    return docs


# Cache at module load time — docs are static, baked into the package.
_CACHED_DOCS = _load_docs()
_CACHED_DOCS_BY_SLUG = {d.slug: d for d in _CACHED_DOCS}


@router.get("", response_model=list[DocResponse])
def list_docs() -> list[DocResponse]:
    """List all available documentation resources."""
    return _CACHED_DOCS


@router.get("/{slug}", response_model=DocResponse)
def get_doc(slug: str) -> DocResponse:
    """Get a single documentation resource by slug."""
    doc = _CACHED_DOCS_BY_SLUG.get(slug)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Doc '{slug}' not found")
    return doc
