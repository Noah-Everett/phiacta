# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Security policy for sandboxed container execution."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SecurityPolicy:
    """Constraints applied to a sandboxed container.

    Defaults are deliberately restrictive: no network, read-only rootfs,
    all capabilities dropped, no new privileges.
    """

    memory_mb: int = 512
    timeout_seconds: int = 120
    max_pids: int = 64
    network_disabled: bool = True
    read_only_rootfs: bool = True
    tmpfs_paths: tuple[str, ...] = ("/tmp",)
    cap_drop: tuple[str, ...] = ("ALL",)
