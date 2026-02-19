# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema

# ---------------------------------------------------------------------------
# Grammar constants
# ---------------------------------------------------------------------------

_UUID_HEX = r"[0-9a-fA-F]"
_UUID_RE = rf"{_UUID_HEX}{{8}}-{_UUID_HEX}{{4}}-{_UUID_HEX}{{4}}-{_UUID_HEX}{{4}}-{_UUID_HEX}{{12}}"
_NUMBER_RE = r"[0-9]+"
_HEX40_RE = rf"{_UUID_HEX}{{40}}"
_NAME_RE = r"[a-zA-Z0-9_/.\-]+"

# Full URI pattern with named groups
_URI_PATTERN = re.compile(
    rf"^(?:"
    # claim URIs (with optional sub-resource)
    rf"claim:(?P<claim_uuid>{_UUID_RE})"
    rf"(?:"
    rf"/issue:(?P<issue_number>{_NUMBER_RE})"
    rf"|/pr:(?P<pr_number>{_NUMBER_RE})"
    rf"|/commit:(?P<commit_sha>{_HEX40_RE})"
    rf"|/branch:(?P<branch_name>{_NAME_RE})"
    rf")?"
    # interaction URIs
    rf"|interaction:(?P<interaction_uuid>{_UUID_RE})"
    # agent URIs
    rf"|agent:(?P<agent_uuid>{_UUID_RE})"
    rf")$"
)


class PhiactaURI(str):
    """Validates and parses Phiacta URIs.

    Grammar::

        uri            = claim_uri | interaction_uri | agent_uri
        claim_uri      = "claim:" uuid ["/" resource]
        resource       = "issue:" number
                       | "pr:" number
                       | "commit:" hex40
                       | "branch:" name
        interaction_uri = "interaction:" uuid
        agent_uri      = "agent:" uuid
        uuid           = hex8 "-" hex4 "-" hex4 "-" hex4 "-" hex12
        number         = digit+
        hex40          = 40 hex chars
        name           = [a-zA-Z0-9_/.-]+

    Properties:
        resource_type: "claim", "issue", "pr", "commit", "branch",
                       "interaction", or "agent"
        claim_id:      The UUID from claim URIs, or None for
                       interaction/agent URIs
        resource_id:   The issue number, PR number, commit SHA,
                       branch name, or None
    """

    _match: re.Match[str]

    def __new__(cls, value: str) -> PhiactaURI:
        match = _URI_PATTERN.match(value)
        if match is None:
            raise ValueError(
                f"Invalid Phiacta URI: {value!r}. "
                f"Expected format: claim:<uuid>[/<resource>], "
                f"interaction:<uuid>, or agent:<uuid>"
            )
        instance = super().__new__(cls, value)
        # Store the match on the instance for property access.
        object.__setattr__(instance, "_match", match)
        return instance

    # ------------------------------------------------------------------
    # Pydantic v2 integration
    # ------------------------------------------------------------------

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        return core_schema.no_info_plain_validator_function(
            cls._pydantic_validate,
            serialization=core_schema.to_string_ser_schema(),
        )

    @classmethod
    def _pydantic_validate(cls, value: Any) -> PhiactaURI:
        if isinstance(value, PhiactaURI):
            return value
        if not isinstance(value, str):
            raise ValueError(
                f"PhiactaURI must be a string, got {type(value).__name__}"
            )
        return cls(value)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def resource_type(self) -> str:
        """Return the resource type of this URI.

        Returns one of: "claim", "issue", "pr", "commit", "branch",
        "interaction", "agent".
        """
        m = self._match
        if m.group("interaction_uuid") is not None:
            return "interaction"
        if m.group("agent_uuid") is not None:
            return "agent"
        # It is a claim URI -- check for sub-resources.
        if m.group("issue_number") is not None:
            return "issue"
        if m.group("pr_number") is not None:
            return "pr"
        if m.group("commit_sha") is not None:
            return "commit"
        if m.group("branch_name") is not None:
            return "branch"
        return "claim"

    @property
    def claim_id(self) -> UUID | None:
        """Extract the claim UUID, or None for interaction/agent URIs."""
        uuid_str = self._match.group("claim_uuid")
        if uuid_str is None:
            return None
        return UUID(uuid_str)

    @property
    def resource_id(self) -> str | None:
        """Return the sub-resource identifier, or None.

        For issue/PR URIs this is the number (as a string).
        For commit URIs this is the 40-char hex SHA.
        For branch URIs this is the branch name.
        For bare claim, interaction, and agent URIs this is None.
        """
        m = self._match
        return (
            m.group("issue_number")
            or m.group("pr_number")
            or m.group("commit_sha")
            or m.group("branch_name")
        )

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"PhiactaURI({str(self)!r})"
