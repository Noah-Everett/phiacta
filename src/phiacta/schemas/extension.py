# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

import ipaddress
import re
from datetime import datetime
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Valid event types that extensions may subscribe to.
ALLOWED_EVENT_TYPES = frozenset(
    {
        "claim.created",
        "claim.updated",
        "relation.created",
        "bundle.submitted",
        "review.added",
    }
)

ALLOWED_EXTENSION_TYPES = frozenset({"ingestion", "analysis", "integration"})

# Maximum size (in characters) for the serialised manifest JSON blob.
_MAX_MANIFEST_SIZE = 65_536  # 64 KiB


# Ports that must never be targeted regardless of environment.
_BLOCKED_PORTS = frozenset({5432, 6379, 3306, 27017, 11211, 9200, 9300})


def _validate_base_url_structure(url: str) -> str:
    """Structural validation applied at schema level (no settings needed).

    Checks scheme, hostname presence, credentials, and blocked ports.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("base_url must use http or https scheme")
    if not parsed.hostname:
        raise ValueError("base_url must include a hostname")
    if parsed.port is not None and parsed.port in _BLOCKED_PORTS:
        raise ValueError("base_url must not target common database ports")
    if parsed.username or parsed.password:
        raise ValueError("base_url must not contain credentials")
    return url


def _is_always_blocked(hostname: str) -> bool:
    """Return True for targets that are dangerous in every environment.

    These are blocked regardless of the allowlist or development mode:
    - Cloud metadata endpoints (169.254.169.254)
    - Loopback addresses (127.x.x.x, ::1)
    - The literal strings ``localhost`` and ``localhost.localdomain``
    """
    lower = hostname.lower()
    if lower in ("localhost", "localhost.localdomain"):
        return True
    try:
        addr = ipaddress.ip_address(hostname)
        if addr.is_loopback:
            return True
        # AWS / GCP / Azure metadata endpoint
        if addr == ipaddress.ip_address("169.254.169.254"):
            return True
    except ValueError:
        pass
    return False


def _is_private_ip(hostname: str) -> bool:
    """Return True if *hostname* is a private, link-local, or reserved IP."""
    try:
        addr = ipaddress.ip_address(hostname)
        return addr.is_private or addr.is_link_local or addr.is_reserved
    except ValueError:
        return False


def _hostname_matches_allowlist(
    hostname: str, allowed_hosts: list[str]
) -> bool:
    """Return True if *hostname* matches any entry in *allowed_hosts*.

    Entries can be:
    - Exact hostnames (``ext-arxiv``)
    - CIDR ranges (``10.0.5.0/24``) -- only matches when hostname is an IP
    """
    lower = hostname.lower()
    for entry in allowed_hosts:
        entry_lower = entry.strip().lower()
        if not entry_lower:
            continue
        # Try as CIDR network
        if "/" in entry_lower:
            try:
                network = ipaddress.ip_network(entry_lower, strict=False)
                try:
                    addr = ipaddress.ip_address(hostname)
                    if addr in network:
                        return True
                except ValueError:
                    pass
            except ValueError:
                pass
        else:
            # Exact hostname match
            if lower == entry_lower:
                return True
    return False


def check_base_url_ssrf(
    url: str,
    *,
    environment: str = "production",
    allowed_hosts: list[str] | None = None,
) -> None:
    """Environment-aware SSRF check. Call from the API layer where settings are available.

    Raises ``ValueError`` if the URL targets a blocked destination.

    Rules:
    1. Always block loopback, metadata endpoint, and ``localhost``.
    2. In development: allow all private IPs (Docker Compose friendly).
    3. In production: block private IPs unless the hostname or IP matches
       an entry in *allowed_hosts*.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("base_url must include a hostname")

    # ---- Universal blocklist (never overridden) ----
    if _is_always_blocked(hostname):
        raise ValueError(
            "base_url must not point to loopback or cloud metadata addresses"
        )

    # ---- Private IP handling ----
    if _is_private_ip(hostname):
        if environment == "development":
            # In dev mode, private IPs are allowed (Docker Compose networking).
            return
        # In production, check the allowlist.
        if allowed_hosts and _hostname_matches_allowlist(hostname, allowed_hosts):
            return
        raise ValueError(
            "base_url must not point to a private or reserved address. "
            "Set EXTENSION_ALLOWED_HOSTS to permit trusted internal hosts."
        )

    # ---- Non-IP hostnames that look internal ----
    # In production, unknown non-public hostnames (no dots, e.g. "db" or
    # "ext-arxiv") could resolve to private IPs on a container network.
    # Allow them only if they're on the allowlist or we're in dev mode.
    if environment != "development" and "." not in hostname:
        if allowed_hosts and _hostname_matches_allowlist(hostname, allowed_hosts):
            return
        raise ValueError(
            f"base_url hostname '{hostname}' looks like an internal service name. "
            "Set EXTENSION_ALLOWED_HOSTS to permit trusted internal hosts."
        )


class ExtensionRegister(BaseModel):
    """Payload sent by an extension to self-register with the backend."""

    name: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    version: str = Field(..., min_length=1, max_length=64)
    extension_type: str
    base_url: str = Field(..., max_length=2048)
    description: str | None = Field(default=None, max_length=1024)
    manifest: dict[str, object] = Field(default_factory=dict)
    subscribed_events: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("extension_type")
    @classmethod
    def validate_extension_type(cls, v: str) -> str:
        if v not in ALLOWED_EXTENSION_TYPES:
            raise ValueError(
                f"extension_type must be one of: {', '.join(sorted(ALLOWED_EXTENSION_TYPES))}"
            )
        return v

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        return _validate_base_url_structure(v)

    @field_validator("subscribed_events")
    @classmethod
    def validate_events(cls, v: list[str]) -> list[str]:
        for event in v:
            if event not in ALLOWED_EVENT_TYPES:
                raise ValueError(
                    f"Unknown event type '{event}'. "
                    f"Allowed: {', '.join(sorted(ALLOWED_EVENT_TYPES))}"
                )
        return v

    @field_validator("manifest")
    @classmethod
    def validate_manifest_size(cls, v: dict[str, object]) -> dict[str, object]:
        import json

        serialized = json.dumps(v, default=str)
        if len(serialized) > _MAX_MANIFEST_SIZE:
            raise ValueError(
                f"manifest exceeds maximum size of {_MAX_MANIFEST_SIZE} characters"
            )
        return v

    @field_validator("version")
    @classmethod
    def validate_version_format(cls, v: str) -> str:
        if not re.match(r"^\d+\.\d+\.\d+", v):
            raise ValueError("version must follow semver format (e.g. 1.0.0)")
        return v


class ExtensionHeartbeat(BaseModel):
    """Heartbeat sent by an extension to indicate it is still alive."""

    status: str = "healthy"

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in ("healthy", "unhealthy"):
            raise ValueError("status must be 'healthy' or 'unhealthy'")
        return v


class ExtensionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    version: str
    extension_type: str
    base_url: str
    description: str | None
    health_status: str
    last_heartbeat: datetime | None
    manifest: dict[str, object]
    subscribed_events: list[str]
    created_at: datetime
    updated_at: datetime
