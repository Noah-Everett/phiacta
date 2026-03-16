# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Entry YAML generation and parsing.

Generates `.phiacta/entry.yaml` content for initial repo commits and parses
it back during webhook ingestion. Uses ``yaml.dump()`` for safe serialization
(no string interpolation — avoids YAML injection).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import yaml


def generate_entry_yaml(
    *,
    entry_id: UUID,
    title: str,
    content_format: str,
    author_id: UUID,
    author_handle: str,
    created_at: datetime,
    tags: list[str] | None = None,
    summary: str | None = None,
    license: str | None = None,
    layout_hint: str | None = None,
) -> str:
    """Generate .phiacta/entry.yaml content from entry metadata.

    Returns a YAML string suitable for committing to the entry's git repo.
    The entry_id in the YAML has an ``ent_`` prefix for human readability.
    """
    data: dict[str, Any] = {
        "entry_id": f"ent_{entry_id}",
        "schema_version": 1,
        "title": title,
        "author": {
            "id": f"usr_{author_id}",
            "name": author_handle,
        },
        "created_at": created_at.isoformat(),
        "content_format": content_format,
    }

    # Optional fields — only include if provided
    if license is not None:
        data["license"] = license
    if tags is not None and len(tags) > 0:
        data["tags"] = tags
    if summary is not None:
        data["summary"] = summary
    if layout_hint is not None:
        data["layout_hint"] = layout_hint

    return yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)


_REQUIRED_FIELDS = {"entry_id", "title", "content_format", "author", "created_at"}


def parse_entry_yaml(yaml_str: str) -> dict[str, Any]:
    """Parse .phiacta/entry.yaml content into a structured dict.

    Raises ``ValueError`` if the YAML is malformed or missing required fields.
    """
    try:
        data = yaml.safe_load(yaml_str)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("entry.yaml must be a YAML mapping")

    missing = _REQUIRED_FIELDS - set(data.keys())
    if missing:
        raise ValueError(f"Missing required fields: {missing}")

    return data
