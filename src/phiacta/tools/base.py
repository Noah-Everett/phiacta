# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Base class for tool handlers that run via the job worker.

Tools that need Docker containers use ``ctx.sandbox.run()``.
Tools that only query the DB use ``ctx.db`` directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from phiacta.jobs.sandbox import Sandbox


@dataclass
class ToolContext:
    """Runtime context passed to tool handlers during job execution."""

    db: AsyncSession
    user_id: UUID
    sandbox: Sandbox


class ToolHandler(ABC):
    """Base class for tool implementations that run via the job worker.

    Subclass this and implement :meth:`run` to create a new tool.
    Register the handler by exposing ``tool_handler = MyHandler()``
    in your tool plugin's ``__init__.py``.
    """

    # If True, this tool is eligible for automatic triggering when
    # entry files change (via .phiacta/verify.yaml in the future).
    file_triggered: bool = False

    @abstractmethod
    async def run(self, input: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        """Execute the tool and return a result dict.

        Raise ``ToolInfraError`` for retryable infrastructure failures
        (Docker daemon down, network issues). All other exceptions are
        treated as permanent failures and will not be retried.
        """
        ...


class ToolError(Exception):
    """Base exception for tool execution errors."""


class ToolInfraError(ToolError):
    """Infrastructure error — retryable (Docker down, timeout, etc.)."""


class ToolUserError(ToolError):
    """User/input error — not retryable (bad input, compilation failure, etc.)."""
