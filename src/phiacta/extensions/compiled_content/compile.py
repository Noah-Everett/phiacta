# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""LaTeX compilation core — used by the compiled_content on_ingest hook."""

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

_CONTENT_DIR = ".phiacta/content/"


@dataclass
class CompileResult:
    success: bool
    log: str
    pdf_bytes: bytes | None = None
    no_source: bool = False  # True when entry has no LaTeX source at all


async def find_latex_source(
    git: ForgejoGitService, entry_id: UUID,
) -> tuple[str, bytes | None]:
    """Find the LaTeX entry point for an entry.

    Checks in order:
    1. Single-file: ``.phiacta/content.tex``
    2. Multi-file: scan ``.phiacta/content/`` for the ``.tex`` file
       containing ``\\documentclass``.
    """
    # Single-file case
    try:
        data = await git.read_file(entry_id, ".phiacta/content.tex")
        return ".phiacta/content.tex", data
    except Exception:
        pass

    # Multi-file case: find the .tex file with \documentclass
    try:
        all_paths = await git.list_tree_paths(entry_id, prefix=_CONTENT_DIR)
        tex_paths = [p for p in all_paths if p.endswith(".tex")]
    except Exception:
        return "", None

    for tex_path in tex_paths:
        try:
            data = await git.read_file(entry_id, tex_path)
            text = data.decode("utf-8", errors="replace")
            if "\\documentclass" in text:
                return tex_path, data
        except Exception:
            continue

    return "", None


async def fetch_project_files(
    git: ForgejoGitService, entry_id: UUID, main_path: str,
) -> dict[str, bytes]:
    """Fetch all files under .phiacta/content/ except the main file.

    Uses the recursive git tree API so subdirectories (figures/, sections/,
    etc.) are discovered in a single request.
    """
    files: dict[str, bytes] = {}
    try:
        file_paths = await git.list_tree_paths(entry_id, prefix=_CONTENT_DIR)
        file_paths = [p for p in file_paths if p != main_path]

        for fpath in file_paths:
            try:
                data = await git.read_file(entry_id, fpath)
                rel = fpath.removeprefix(_CONTENT_DIR)
                files[rel] = data
            except Exception:
                pass
    except Exception:
        pass
    return files


async def run_tectonic(
    main_filename: str,
    source: bytes,
    extra_files: dict[str, bytes],
) -> CompileResult:
    """Run tectonic and return the result."""
    with TemporaryDirectory(prefix="phiacta-latex-") as tmpdir:
        work = Path(tmpdir)

        (work / main_filename).write_bytes(source)
        for rel_path, data in extra_files.items():
            dest = work / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        tex_file = str(work / main_filename)

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
            log="No LaTeX source found (no .tex file with \\documentclass)",
            no_source=True,
        )

    is_multifile = source_path.startswith(_CONTENT_DIR)
    extra_files: dict[str, bytes] = {}

    if is_multifile:
        # Main file is e.g. ".phiacta/content/paper.tex" → filename "paper.tex"
        main_filename = source_path.removeprefix(_CONTENT_DIR)
        extra_files = await fetch_project_files(git, entry_id, source_path)
    else:
        # Single file: ".phiacta/content.tex"
        main_filename = "content.tex"

    return await run_tectonic(main_filename, source_bytes, extra_files)
