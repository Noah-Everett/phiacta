# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""FastAPI dependency for injecting the GitService.

Provides ``get_git_service()`` which returns the active ``GitService``
implementation. Tests override this dependency to inject a FakeGitService.
"""

from __future__ import annotations

from phiacta.core.services.git_service import ForgejoGitService, GitService

# Module-level singleton — created on first use, reused across requests.
# The httpx.AsyncClient inside ForgejoGitService is designed for reuse.
_instance: ForgejoGitService | None = None


def get_git_service() -> GitService:
    """Return the GitService instance for the current request.

    Uses a module-level singleton so the underlying httpx.AsyncClient is
    reused across requests. Tests override this via
    ``app.dependency_overrides[get_git_service]``.
    """
    global _instance
    if _instance is None:
        _instance = ForgejoGitService()
    return _instance


async def close_git_service() -> None:
    """Close the singleton GitService's httpx client.

    Called during application shutdown to release connections.
    """
    global _instance
    if _instance is not None:
        await _instance.close()
        _instance = None
