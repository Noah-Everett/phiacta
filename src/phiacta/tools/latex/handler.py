# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""LaTeX compilation handler — reads .tex source from an entry's git repo,
compiles with tectonic, and stores the output PDF via the compiled_content
extension."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID

from phiacta.core.services.git_service import ForgejoGitService
from phiacta.extensions.compiled_content.repository import CompiledContentRepository
from phiacta.tools.base import ToolContext, ToolHandler, ToolInfraError

logger = logging.getLogger(__name__)

_COMPILE_TIMEOUT = 120  # seconds

# Paths to check for LaTeX source (in priority order)
_SOURCE_PATHS = [
    ".phiacta/content.tex",
    ".phiacta/content/main.tex",
]


class LatexHandler(ToolHandler):
    """Compile an entry's LaTeX source to PDF.

    Checks for ``.phiacta/content.tex`` (single file) or
    ``.phiacta/content/main.tex`` (multi-file project). Compiles with
    tectonic and stores the PDF via the compiled_content extension.
    """

    def __init__(self) -> None:
        self._git: ForgejoGitService | None = None

    def _get_git(self) -> ForgejoGitService:
        if self._git is None:
            self._git = ForgejoGitService()
        return self._git

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        entry_id = UUID(str(input["entry_id"]))
        git = self._get_git()

        # Find the source file
        source_path, source_bytes = await self._find_source(git, entry_id)
        if source_bytes is None:
            return {
                "success": False,
                "log": f"No LaTeX source found. Checked: {', '.join(_SOURCE_PATHS)}",
            }

        # For multi-file projects, also fetch supporting files
        is_multifile = "content/" in source_path
        extra_files: dict[str, bytes] = {}
        if is_multifile:
            extra_files = await self._fetch_project_files(git, entry_id)

        # Compile
        pdf_bytes, log, success = await self._compile(
            source_bytes, extra_files, is_multifile,
        )

        if not success or pdf_bytes is None:
            return {"success": False, "log": log}

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
            data=pdf_bytes,
            source_sha=source_sha,
        )

        logger.info(
            "LaTeX compiled for entry %s (%d bytes PDF)", entry_id, len(pdf_bytes),
        )

        return {"success": True, "log": log, "file_size": len(pdf_bytes)}

    async def _find_source(
        self, git: ForgejoGitService, entry_id: UUID,
    ) -> tuple[str, bytes | None]:
        """Try each source path and return the first that exists."""
        for path in _SOURCE_PATHS:
            try:
                data = await git.read_file(entry_id, path)
                return path, data
            except Exception:
                continue
        return "", None

    async def _fetch_project_files(
        self, git: ForgejoGitService, entry_id: UUID,
    ) -> dict[str, bytes]:
        """Fetch all files under .phiacta/content/ for multi-file projects."""
        files: dict[str, bytes] = {}
        try:
            listing = await git.list_files(entry_id, ".phiacta/content")
            for item in listing:
                if item.type == "file" and item.name != "main.tex":
                    try:
                        data = await git.read_file(entry_id, item.path)
                        # Store relative to content dir
                        rel = item.path.removeprefix(".phiacta/content/")
                        files[rel] = data
                    except Exception:
                        pass
        except Exception:
            pass
        return files

    async def _compile(
        self,
        source: bytes,
        extra_files: dict[str, bytes],
        is_multifile: bool,
    ) -> tuple[bytes | None, str, bool]:
        """Run tectonic and return (pdf_bytes, log, success)."""
        with TemporaryDirectory(prefix="phiacta-latex-") as tmpdir:
            work = Path(tmpdir)

            if is_multifile:
                # Write all files maintaining directory structure
                (work / "main.tex").write_bytes(source)
                for rel_path, data in extra_files.items():
                    dest = work / rel_path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
                tex_file = str(work / "main.tex")
            else:
                (work / "content.tex").write_bytes(source)
                tex_file = str(work / "content.tex")

            proc = await asyncio.create_subprocess_exec(
                "tectonic", "-X", "compile", tex_file,
                cwd=str(work),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=_COMPILE_TIMEOUT,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise ToolInfraError(f"tectonic timed out after {_COMPILE_TIMEOUT}s")

            log = (stdout.decode(errors="replace") + stderr.decode(errors="replace")).strip()

            if proc.returncode != 0:
                return None, log, False

            # Find the output PDF (tectonic puts it next to the .tex file)
            pdf_name = Path(tex_file).stem + ".pdf"
            pdf_path = work / pdf_name
            if not pdf_path.exists():
                return None, log + "\nNo PDF output produced", False

            return pdf_path.read_bytes(), log, True
