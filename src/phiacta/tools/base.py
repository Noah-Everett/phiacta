# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Base class for job handlers that run via the job worker.

Any plugin (extension or tool) can expose a ``job_handler`` to run
asynchronous work through the job queue. Handlers that need Docker
containers use ``ctx.sandbox.run()``; those that only query the DB
use ``ctx.db`` directly.
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
class JobContext:
    """Runtime context passed to job handlers during execution."""

    db: AsyncSession
    user_id: UUID
    sandbox: Sandbox


class JobHandler(ABC):
    """Base class for job handler implementations.

    Subclass this and implement :meth:`run` to create a new handler.
    Register it by exposing ``job_handler = MyHandler()`` in your
    plugin's ``__init__.py``.
    """

    # If True, this handler is eligible for automatic triggering when
    # entry files change (via .phiacta/verify.yaml in the future).
    file_triggered: bool = False

    @abstractmethod
    async def run(self, input: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        """Execute the handler and return a result dict.

        Raise ``JobInfraError`` for retryable infrastructure failures
        (Docker daemon down, network issues). All other exceptions are
        treated as permanent failures and will not be retried.
        """
        ...


class JobError(Exception):
    """Base exception for job execution errors."""


class JobInfraError(JobError):
    """Infrastructure error — retryable (Docker down, timeout, etc.)."""


class JobUserError(JobError):
    """User/input error — not retryable (bad input, compilation failure, etc.)."""
