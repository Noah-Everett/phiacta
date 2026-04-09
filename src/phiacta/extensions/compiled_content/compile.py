# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""LaTeX compilation core — shared by the on_ingest hook and the manual
compile tool endpoint."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from phiacta.core.services.git_service import ForgejoGitService

logger = logging.getLogger(__name__)

_COMPILE_TIMEOUT = 120  # seconds

# Paths to check for LaTeX source (in priority order)
_SOURCE_PATHS = [
    ".phiacta/content.tex",
    ".phiacta/content/main.tex",
]


@dataclass
class CompileResult:
    success: bool
    log: str
    pdf_bytes: bytes | None = None


async def find_latex_source(
    git: ForgejoGitService, entry_id: UUID,
) -> tuple[str, bytes | None]:
    """Try each source path and return the first that exists."""
    for path in _SOURCE_PATHS:
        try:
            data = await git.read_file(entry_id, path)
            return path, data
        except Exception:
            continue
    return "", None


async def fetch_project_files(
    git: ForgejoGitService, entry_id: UUID,
) -> dict[str, bytes]:
    """Fetch all files under .phiacta/content/ for multi-file projects.

    Uses the recursive git tree API so subdirectories (figures/, sections/,
    etc.) are discovered in a single request.
    """
    prefix = ".phiacta/content/"
    files: dict[str, bytes] = {}
    try:
        file_paths = await git.list_tree_paths(entry_id, prefix=prefix)
        file_paths = [p for p in file_paths if p != f"{prefix}main.tex"]

        for fpath in file_paths:
            try:
                data = await git.read_file(entry_id, fpath)
                rel = fpath.removeprefix(prefix)
                files[rel] = data
            except Exception:
                pass
    except Exception:
        pass
    return files


async def run_tectonic(
    source: bytes,
    extra_files: dict[str, bytes],
    is_multifile: bool,
) -> CompileResult:
    """Run tectonic and return the result."""
    with TemporaryDirectory(prefix="phiacta-latex-") as tmpdir:
        work = Path(tmpdir)

        if is_multifile:
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
            return CompileResult(
                success=False,
                log=f"tectonic timed out after {_COMPILE_TIMEOUT}s",
            )

        log = (stdout.decode(errors="replace") + stderr.decode(errors="replace")).strip()

        if proc.returncode != 0:
            return CompileResult(success=False, log=log)

        pdf_name = Path(tex_file).stem + ".pdf"
        pdf_path = work / pdf_name
        if not pdf_path.exists():
            return CompileResult(success=False, log=log + "\nNo PDF output produced")

        return CompileResult(
            success=True,
            log=log,
            pdf_bytes=pdf_path.read_bytes(),
        )


async def compile_entry(
    entry_id: UUID, git: ForgejoGitService | None = None,
) -> CompileResult:
    """Find LaTeX source for an entry, compile it, and return the result.

    Does NOT store the PDF — the caller is responsible for that.
    """
    if git is None:
        git = ForgejoGitService()

    source_path, source_bytes = await find_latex_source(git, entry_id)
    if source_bytes is None:
        return CompileResult(
            success=False,
            log=f"No LaTeX source found. Checked: {', '.join(_SOURCE_PATHS)}",
        )

    is_multifile = "content/" in source_path
    extra_files: dict[str, bytes] = {}
    if is_multifile:
        extra_files = await fetch_project_files(git, entry_id)

    return await run_tectonic(source_bytes, extra_files, is_multifile)
