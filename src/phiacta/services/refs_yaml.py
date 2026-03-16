# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Refs YAML parsing for webhook ingestion.

Parses `.phiacta/refs.yaml` content from an entry's git repository into a
structured list of reference descriptors. Used by the webhook handler to
sync outgoing entry_refs.
"""

from __future__ import annotations

from typing import Any


def parse_refs_yaml(yaml_str: str) -> list[dict[str, Any]]:
    """Parse .phiacta/refs.yaml content into a list of ref descriptors.

    Each ref descriptor has keys: rel, target (dict with entry_id),
    and optionally note and version_sha.

    Raises ``ValueError`` if the YAML is malformed or structurally invalid.

    Stub -- implementation pending. All tests should FAIL against this stub.
    """
    raise NotImplementedError("parse_refs_yaml not yet implemented")
