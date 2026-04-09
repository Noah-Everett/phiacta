# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""CompileHandler — runs LaTeX compilation via the job worker."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import httpx

from phiacta.core.repositories.entry_repository import EntryRepository
from phiacta.core.services.git_service import ForgejoGitService, ForgejoUnavailableError
from phiacta.extensions.compiled_content.compile import compile_entry
from phiacta.extensions.compiled_content.repository import CompiledContentRepository
from phiacta.tools.base import ToolContext, ToolHandler, ToolInfraError, ToolUserError

logger = logging.getLogger(__name__)


class CompileHandler(ToolHandler):
    """Compiles LaTeX entries and stores the resulting PDF."""

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        entry_id = UUID(input["entry_id"])

        # Check entry still exists
        entry = await EntryRepository(ctx.db).get_by_id(entry_id)
        if entry is None:
            return {"status": "skipped", "reason": "entry_not_found"}

        source_sha = entry.current_head_sha or "unknown"

        # Compile — wrap infrastructure errors for retry
        try:
            git = ForgejoGitService()
            result = await compile_entry(entry_id, git=git)
        except (ForgejoUnavailableError, httpx.ConnectError, httpx.TimeoutException) as exc:
            raise ToolInfraError(f"Git service unavailable: {exc}") from exc
        except FileNotFoundError as exc:
            raise ToolInfraError(f"tectonic binary not found: {exc}") from exc

        if result.no_source:
            return {"status": "skipped", "reason": "no_latex_source"}

        if not result.success or result.pdf_bytes is None:
            raise ToolUserError(f"LaTeX compilation failed: {result.log[:500]}")

        # Guard against stale overwrites: if the entry has moved on since
        # this job was submitted, skip the upsert.
        entry_now = await EntryRepository(ctx.db).get_by_id(entry_id)
        if entry_now is not None and entry_now.current_head_sha != source_sha:
            logger.info(
                "Skipping stale compilation for entry %s (compiled %s, HEAD now %s)",
                entry_id, source_sha, entry_now.current_head_sha,
            )
            return {"status": "skipped", "reason": "stale_sha"}

        await CompiledContentRepository(ctx.db).upsert(
            entry_id=entry_id,
            format="pdf",
            data=result.pdf_bytes,
            source_sha=source_sha,
        )

        logger.info(
            "Compiled entry %s (%d bytes PDF, sha=%s)",
            entry_id, len(result.pdf_bytes), source_sha,
        )

        return {
            "status": "compiled",
            "file_size": len(result.pdf_bytes),
            "source_sha": source_sha,
        }
