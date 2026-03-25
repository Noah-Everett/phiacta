# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Entry YAML generation and parsing — identity fields only."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import yaml


def generate_entry_yaml(
    *, entry_id: UUID, schema_version: int = 1,
    author_id: UUID, author_name: str, created_at: datetime,
) -> str:
    data: dict[str, Any] = {
        "entry_id": f"ent_{entry_id}",
        "schema_version": schema_version,
        "author": {"id": f"usr_{author_id}", "name": author_name},
        "created_at": created_at.isoformat(),
    }
    return yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)


_REQUIRED_FIELDS = {"entry_id", "author", "created_at"}


def parse_entry_yaml(yaml_str: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(yaml_str)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("entry.yaml must be a YAML mapping")
    missing = _REQUIRED_FIELDS - set(data.keys())
    if missing:
        raise ValueError(f"Missing required fields: {missing}")

    raw_entry_id = str(data.get("entry_id", ""))
    if raw_entry_id.startswith("ent_"):
        raw_entry_id = raw_entry_id[4:]
    try:
        entry_id = UUID(raw_entry_id)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid entry_id: {data.get('entry_id')}") from exc

    author = data.get("author", {})
    if not isinstance(author, dict):
        raise ValueError("author must be a mapping")
    raw_author_id = str(author.get("id", ""))
    if raw_author_id.startswith("usr_"):
        raw_author_id = raw_author_id[4:]
    try:
        author_id = UUID(raw_author_id)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid author.id: {author.get('id')}") from exc

    return {
        "entry_id": entry_id,
        "schema_version": data.get("schema_version", 1),
        "author_id": author_id,
        "author_name": str(author.get("name", "")),
        "created_at": data.get("created_at"),
        **{k: v for k, v in data.items() if k not in ("entry_id", "author")},
    }
