# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""LaTeX compilation tool handler — manual recompile endpoint.

Delegates to the shared compile module in the compiled_content extension.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from phiacta.core.services.git_service import ForgejoGitService
from phiacta.extensions.compiled_content.compile import compile_entry
from phiacta.extensions.compiled_content.repository import CompiledContentRepository
from phiacta.tools.base import ToolContext, ToolHandler

logger = logging.getLogger(__name__)


class LatexHandler(ToolHandler):
    """Compile an entry's LaTeX source to PDF (manual trigger)."""

    def __init__(self) -> None:
        self._git: ForgejoGitService | None = None

    def _get_git(self) -> ForgejoGitService:
        if self._git is None:
            self._git = ForgejoGitService()
        return self._git

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        entry_id = UUID(str(input["entry_id"]))

        result = await compile_entry(entry_id, git=self._get_git())

        if not result.success or result.pdf_bytes is None:
            return {"success": False, "log": result.log}

        # Get current HEAD SHA for cache key
        from phiacta.core.repositories.entry_repository import EntryRepository

        entry_repo = EntryRepository(ctx.db)
        entry = await entry_repo.get_by_id(entry_id)
        source_sha = entry.current_head_sha if entry else "unknown"

        # Store via compiled_content extension
        cc_repo = CompiledContentRepository(ctx.db)
        await cc_repo.upsert(
            entry_id=entry_id,
            format="pdf",
            data=result.pdf_bytes,
            source_sha=source_sha,
        )

        logger.info(
            "LaTeX compiled for entry %s (%d bytes PDF)", entry_id, len(result.pdf_bytes),
        )

        return {"success": True, "log": result.log, "file_size": len(result.pdf_bytes)}
