# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""FastAPI dependency for injecting the GitService.

Provides ``get_git_service()`` which returns the active ``GitService``
implementation. Tests override this dependency to inject a FakeGitService.
"""

from __future__ import annotations

from phiacta.services.git_service import ForgejoGitService, GitService


def get_git_service() -> GitService:
    """Return the GitService instance for the current request.

    Stub -- implementation pending. All tests should FAIL against this stub.
    """
    raise NotImplementedError("get_git_service not yet implemented")
