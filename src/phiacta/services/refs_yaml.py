# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Refs YAML parsing for webhook ingestion.

Parses `.phiacta/refs.yaml` content from an entry's git repository into a
structured list of reference descriptors. Used by the webhook handler to
sync outgoing entry_refs.
"""

from __future__ import annotations

from typing import Any

import yaml


def parse_refs_yaml(yaml_str: str) -> list[dict[str, Any]]:
    """Parse .phiacta/refs.yaml content into a list of ref descriptors.

    Each ref descriptor has keys: ``rel``, ``target`` (dict with ``entry_id``),
    and optionally ``note`` and ``version_sha``.

    Raises ``ValueError`` if the YAML is malformed or structurally invalid.
    """
    try:
        data = yaml.safe_load(yaml_str)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("refs.yaml must be a YAML mapping")

    if "refs" not in data:
        raise ValueError("refs.yaml missing required 'refs' key")

    refs_list = data["refs"]
    if not isinstance(refs_list, list):
        raise ValueError("refs.yaml 'refs' must be a list")

    result: list[dict[str, Any]] = []
    for i, ref in enumerate(refs_list):
        if not isinstance(ref, dict):
            raise ValueError(f"refs[{i}] must be a mapping")
        if "rel" not in ref:
            raise ValueError(f"refs[{i}] missing required 'rel' field")
        if "target" not in ref:
            raise ValueError(f"refs[{i}] missing required 'target' field")

        target = ref["target"]
        if not isinstance(target, dict):
            raise ValueError(f"refs[{i}].target must be a mapping")
        if "entry_id" not in target:
            raise ValueError(f"refs[{i}].target missing required 'entry_id' field")

        # Strip ent_ prefix for to_entry_id (used by webhook handler)
        raw_entry_id = str(target["entry_id"])
        stripped_id = raw_entry_id[4:] if raw_entry_id.startswith("ent_") else raw_entry_id

        result.append({
            "rel": ref["rel"],
            "target": target,
            "to_entry_id": stripped_id,
            "note": ref.get("note"),
            "version_sha": ref.get("version_sha"),
        })

    return result
