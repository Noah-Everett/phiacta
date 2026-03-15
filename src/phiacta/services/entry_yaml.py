# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Entry YAML generation and parsing.

Stub -- implementation pending. All tests should FAIL against this stub.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID


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
    The entry_id in the YAML must have an 'ent_' prefix.
    """
    raise NotImplementedError("generate_entry_yaml not yet implemented")


def parse_entry_yaml(yaml_str: str) -> dict[str, object]:
    """Parse .phiacta/entry.yaml content into a structured dict.

    Raises an exception if the YAML is malformed or missing required fields
    (entry_id, title, content_format, author, created_at).
    """
    raise NotImplementedError("parse_entry_yaml not yet implemented")
