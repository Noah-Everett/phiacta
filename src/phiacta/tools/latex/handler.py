# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""LaTeX compilation handler — reads .tex source from an entry's git repo,
compiles with tectonic, and commits the output PDF back."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID

from phiacta.core.services.git_service import AuthorInfo, FileContent, ForgejoGitService
from phiacta.tools.base import ToolContext, ToolHandler, ToolInfraError

logger = logging.getLogger(__name__)

_PDF_PATH = ".phiacta/output.pdf"
_COMPILE_TIMEOUT = 120  # seconds


class LatexHandler(ToolHandler):
    """Compile an entry's LaTeX source to PDF.

    Reads ``.phiacta/content.tex`` from the entry's git repo, runs
    ``tectonic`` as a subprocess, and commits the resulting PDF back
    to ``.phiacta/output.pdf``.
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

        # Read the source .tex file
        try:
            source = await git.read_file(entry_id, ".phiacta/content.tex")
        except Exception as exc:
            return {"success": False, "log": f"Could not read .phiacta/content.tex: {exc}", "pdf_path": None}

        # Compile in a temp directory
        with TemporaryDirectory(prefix="phiacta-latex-") as tmpdir:
            tex_path = Path(tmpdir) / "content.tex"
            tex_path.write_bytes(source)

            proc = await asyncio.create_subprocess_exec(
                "tectonic", "-X", "compile", str(tex_path),
                cwd=tmpdir,
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

            combined_log = stdout.decode(errors="replace") + stderr.decode(errors="replace")

            if proc.returncode != 0:
                return {"success": False, "log": combined_log.strip(), "pdf_path": None}

            pdf_path = Path(tmpdir) / "content.pdf"
            if not pdf_path.exists():
                return {"success": False, "log": "Compilation succeeded but no PDF was produced", "pdf_path": None}

            pdf_bytes = pdf_path.read_bytes()

        # Commit the PDF back to the entry's git repo
        author = AuthorInfo(name="phiacta-latex", email="latex@phiacta.local")
        await git.commit_files(
            entry_id,
            [FileContent(path=_PDF_PATH, content=pdf_bytes)],
            author,
            "Compile LaTeX → PDF",
        )

        logger.info("LaTeX compilation succeeded for entry %s (%d bytes)", entry_id, len(pdf_bytes))

        return {"success": True, "log": combined_log.strip(), "pdf_path": _PDF_PATH}
