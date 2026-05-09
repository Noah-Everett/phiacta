# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""LaTeX compilation core.

Supports two modes:
- **git clone** (preferred): clones the entry repo and compiles in-place.
  Fast for large multi-file projects. Requires ``git`` on PATH.
- **API fallback**: fetches files one-by-one via the Forgejo API.
  Used when git is not available (e.g. dev/test without git installed).

Compiler priority: ``latexmk`` (TeX Live) > ``tectonic``.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from phiacta.config import get_settings
from phiacta.core.services.git_service import ForgejoGitService

logger = logging.getLogger(__name__)

_COMPILE_TIMEOUT = 300  # seconds (large papers need more time)
_CLONE_TIMEOUT = 120  # seconds

_CONTENT_DIR = ".phiacta/content/"

# Environment variables to restrict TeX Live file access (paranoid mode).
# openin_any=p: only read files in the working tree and $TEXMF directories.
# openout_any=p: only write files in the working tree.
_LATEX_SAFE_ENV: dict[str, str] = {
    "openin_any": "p",
    "openout_any": "p",
}


def _redact_credentials(text: str) -> str:
    """Strip the Forgejo admin password from text before logging."""
    password = get_settings().forgejo_admin_password
    if password:
        text = text.replace(password, "***")
    return text


@dataclass
class CompileResult:
    success: bool
    log: str
    pdf_bytes: bytes | None = None
    no_source: bool = False  # True when entry has no LaTeX source at all


# ---------------------------------------------------------------------------
# Git clone — fast path for multi-file projects
# ---------------------------------------------------------------------------


async def _clone_repo(entry_id: UUID, dest: Path) -> bool:
    """Clone an entry repo into *dest*. Returns True on success."""
    settings = get_settings()
    user = settings.forgejo_admin_user
    password = settings.forgejo_admin_password
    org = settings.forgejo_org
    base = settings.forgejo_url

    # Build authenticated clone URL
    # http://user:pass@forgejo:3000/org/repo-name.git
    scheme_rest = base.split("://", 1)
    clone_url = f"{scheme_rest[0]}://{user}:{password}@{scheme_rest[1]}/{org}/{entry_id}.git"

    proc = await asyncio.create_subprocess_exec(
        "git", "clone", "--depth=1", "--single-branch", clone_url, str(dest),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_CLONE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        logger.warning("git clone timed out for entry %s", entry_id)
        return False

    if proc.returncode != 0:
        logger.warning(
            "git clone failed for entry %s: %s",
            entry_id, _redact_credentials(stderr.decode(errors="replace")[:500]),
        )
        return False

    return True


def _has_git() -> bool:
    return shutil.which("git") is not None


# ---------------------------------------------------------------------------
# Find LaTeX source
# ---------------------------------------------------------------------------


def _find_latex_source_on_disk(repo_dir: Path) -> tuple[str, Path | None]:
    """Find the LaTeX entry point in a cloned repo directory."""
    # Single-file case
    single = repo_dir / ".phiacta" / "content.tex"
    if single.exists():
        return "content.tex", single

    # Multi-file case
    content_dir = repo_dir / ".phiacta" / "content"
    if not content_dir.is_dir():
        return "", None

    for tex_file in content_dir.rglob("*.tex"):
        text = tex_file.read_text(errors="replace")
        if "\\documentclass" in text:
            return str(tex_file.relative_to(content_dir)), tex_file

    return "", None


async def _find_latex_source_api(
    git: ForgejoGitService, entry_id: UUID,
) -> tuple[str, bytes | None]:
    """Find the LaTeX entry point via the Forgejo API (fallback)."""
    # Single-file case
    try:
        data = await git.read_file(entry_id, ".phiacta/content.tex")
        return ".phiacta/content.tex", data
    except Exception:
        pass

    # Multi-file case
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


# ---------------------------------------------------------------------------
# Compile
# ---------------------------------------------------------------------------


async def _run_latexmk(tex_file: Path, work_dir: Path) -> CompileResult:
    """Compile with latexmk (TeX Live). Preferred compiler."""
    import os

    # Pass a relative path so openin_any=p (paranoid mode) doesn't block
    # reads. Absolute paths like /tmp/.../main.tex trigger pdflatex's
    # security check even when the file is inside the working directory.
    tex_rel = tex_file.relative_to(work_dir)
    env = {**os.environ, **_LATEX_SAFE_ENV}
    proc = await asyncio.create_subprocess_exec(
        "latexmk", "-pdf", "-interaction=nonstopmode",
        "-halt-on-error", "-no-shell-escape", str(tex_rel),
        cwd=str(work_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
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
            log=f"latexmk timed out after {_COMPILE_TIMEOUT}s",
        )

    log = (stdout.decode(errors="replace") + stderr.decode(errors="replace")).strip()

    pdf_path = tex_file.with_suffix(".pdf")
    if not pdf_path.exists():
        # Check work_dir root too (latexmk sometimes puts output there)
        pdf_path = work_dir / tex_file.with_suffix(".pdf").name

    if proc.returncode != 0 or not pdf_path.exists():
        return CompileResult(success=False, log=log)

    return CompileResult(
        success=True,
        log=log,
        pdf_bytes=pdf_path.read_bytes(),
    )


async def _run_tectonic(tex_file: Path, work_dir: Path) -> CompileResult:
    """Compile with Tectonic. Fallback when TeX Live is not installed."""
    import os

    tex_rel = tex_file.relative_to(work_dir)
    env = {**os.environ, **_LATEX_SAFE_ENV}
    proc = await asyncio.create_subprocess_exec(
        "tectonic", "-X", "compile", str(tex_rel),
        cwd=str(work_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
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

    pdf_path = tex_file.with_suffix(".pdf")
    if not pdf_path.exists():
        return CompileResult(success=False, log=log + "\nNo PDF output produced")

    return CompileResult(success=True, log=log, pdf_bytes=pdf_path.read_bytes())


async def _compile_in_dir(main_rel: str, work_dir: Path) -> CompileResult:
    """Compile the LaTeX source in *work_dir* using the best available compiler."""
    tex_file = work_dir / main_rel

    if shutil.which("latexmk"):
        return await _run_latexmk(tex_file, work_dir)
    elif shutil.which("tectonic"):
        return await _run_tectonic(tex_file, work_dir)
    else:
        raise FileNotFoundError(
            "No LaTeX compiler found (need latexmk or tectonic on PATH)"
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def compile_entry(
    entry_id: UUID, git: ForgejoGitService | None = None,
) -> CompileResult:
    """Find LaTeX source for an entry, compile it, and return the result.

    Uses git clone when available (fast), falls back to API file fetching.
    Does NOT store the PDF — the caller is responsible for that.
    """
    if git is None:
        git = ForgejoGitService()

    # Fast path: git clone
    if _has_git():
        return await _compile_via_clone(entry_id)

    # Fallback: API file fetching (one-by-one)
    return await _compile_via_api(entry_id, git)


async def _compile_via_clone(entry_id: UUID) -> CompileResult:
    """Clone the repo and compile locally."""
    with TemporaryDirectory(prefix="phiacta-latex-") as tmpdir:
        repo_dir = Path(tmpdir) / "repo"

        if not await _clone_repo(entry_id, repo_dir):
            return CompileResult(
                success=False,
                log="Failed to clone entry repository",
            )

        main_rel, main_path = _find_latex_source_on_disk(repo_dir)
        if main_path is None:
            return CompileResult(
                success=False,
                log="No LaTeX source found (no .tex file with \\documentclass)",
                no_source=True,
            )

        # Determine working directory
        content_dir = repo_dir / ".phiacta" / "content"
        if content_dir.is_dir() and main_path.is_relative_to(content_dir):
            work_dir = content_dir
        else:
            work_dir = repo_dir / ".phiacta"

        return await _compile_in_dir(main_rel, work_dir)


async def _compile_via_api(
    entry_id: UUID, git: ForgejoGitService,
) -> CompileResult:
    """Fetch files via API and compile in a temp directory (fallback)."""
    source_path, source_bytes = await _find_latex_source_api(git, entry_id)
    if source_bytes is None:
        return CompileResult(
            success=False,
            log="No LaTeX source found (no .tex file with \\documentclass)",
            no_source=True,
        )

    is_multifile = source_path.startswith(_CONTENT_DIR)

    with TemporaryDirectory(prefix="phiacta-latex-") as tmpdir:
        work = Path(tmpdir)

        if is_multifile:
            main_filename = source_path.removeprefix(_CONTENT_DIR)
            # Fetch all project files
            try:
                file_paths = await git.list_tree_paths(
                    entry_id, prefix=_CONTENT_DIR,
                )
                for fpath in file_paths:
                    try:
                        data = await git.read_file(entry_id, fpath)
                        rel = fpath.removeprefix(_CONTENT_DIR)
                        dest = work / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(data)
                    except Exception:
                        pass
            except Exception:
                pass
        else:
            main_filename = "content.tex"
            (work / main_filename).write_bytes(source_bytes)

        return await _compile_in_dir(main_filename, work)
