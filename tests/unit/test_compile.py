# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Tests for compiled_content/compile.py — LaTeX source discovery and
compiler selection logic.

Tests _find_latex_source_on_disk (pure filesystem function) and
_compile_in_dir (compiler dispatch).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from phiacta.extensions.compiled_content.compile import (
    CompileResult,
    _compile_in_dir,
    _find_latex_source_on_disk,
)


# --- _find_latex_source_on_disk ---------------------------------------------


class TestFindLatexSourceOnDisk:
    def test_single_file_content_tex(self, tmp_path: Path) -> None:
        """Single-file case: .phiacta/content.tex exists."""
        tex = tmp_path / ".phiacta" / "content.tex"
        tex.parent.mkdir(parents=True)
        tex.write_text(r"\documentclass{article}")

        rel, path = _find_latex_source_on_disk(tmp_path)
        assert rel == "content.tex"
        assert path == tex

    def test_multi_file_main_tex(self, tmp_path: Path) -> None:
        """Multi-file case: .phiacta/content/main.tex with \\documentclass."""
        content_dir = tmp_path / ".phiacta" / "content"
        content_dir.mkdir(parents=True)
        main = content_dir / "main.tex"
        main.write_text(r"\documentclass{article}\begin{document}Hi\end{document}")

        rel, path = _find_latex_source_on_disk(tmp_path)
        assert rel == "main.tex"
        assert path == main

    def test_nested_multi_file(self, tmp_path: Path) -> None:
        """Nested multi-file: .phiacta/content/src/paper.tex."""
        src_dir = tmp_path / ".phiacta" / "content" / "src"
        src_dir.mkdir(parents=True)
        paper = src_dir / "paper.tex"
        paper.write_text(r"\documentclass[12pt]{report}")

        rel, path = _find_latex_source_on_disk(tmp_path)
        assert rel == "src/paper.tex"
        assert path == paper

    def test_no_phiacta_dir(self, tmp_path: Path) -> None:
        """No .phiacta directory at all."""
        rel, path = _find_latex_source_on_disk(tmp_path)
        assert rel == ""
        assert path is None

    def test_content_dir_no_tex_files(self, tmp_path: Path) -> None:
        """Content dir exists but has only non-tex files."""
        content_dir = tmp_path / ".phiacta" / "content"
        content_dir.mkdir(parents=True)
        (content_dir / "README.md").write_text("# Readme")

        rel, path = _find_latex_source_on_disk(tmp_path)
        assert rel == ""
        assert path is None

    def test_tex_files_without_documentclass(self, tmp_path: Path) -> None:
        """Multi-file case: .tex files exist but none contain \\documentclass."""
        content_dir = tmp_path / ".phiacta" / "content"
        content_dir.mkdir(parents=True)
        (content_dir / "helper.tex").write_text(r"\input{macros}" + "\n" + r"\newcommand{\foo}{bar}")
        (content_dir / "macros.tex").write_text(r"\newcommand{\baz}{qux}")

        rel, path = _find_latex_source_on_disk(tmp_path)
        assert rel == ""
        assert path is None

    def test_single_file_wins_over_multi_file(self, tmp_path: Path) -> None:
        """When both content.tex and content/main.tex exist, single-file wins."""
        phiacta = tmp_path / ".phiacta"
        phiacta.mkdir()
        single = phiacta / "content.tex"
        single.write_text(r"\documentclass{article}")
        content_dir = phiacta / "content"
        content_dir.mkdir()
        (content_dir / "main.tex").write_text(r"\documentclass{report}")

        rel, path = _find_latex_source_on_disk(tmp_path)
        assert rel == "content.tex"
        assert path == single


# --- _compile_in_dir --------------------------------------------------------


class TestCompileInDir:
    async def test_prefers_latexmk(self, tmp_path: Path) -> None:
        """When latexmk is available, uses it over tectonic."""
        tex_file = tmp_path / "main.tex"
        tex_file.write_text(r"\documentclass{article}")
        expected = CompileResult(success=True, log="ok", pdf_bytes=b"%PDF")

        def _which(name: str) -> str | None:
            return "/usr/bin/latexmk" if name == "latexmk" else None

        with (
            patch("shutil.which", side_effect=_which),
            patch(
                "phiacta.extensions.compiled_content.compile._run_latexmk",
                new_callable=AsyncMock,
                return_value=expected,
            ) as mock_latexmk,
            patch(
                "phiacta.extensions.compiled_content.compile._run_tectonic",
                new_callable=AsyncMock,
            ) as mock_tectonic,
        ):
            result = await _compile_in_dir("main.tex", tmp_path)

        assert result is expected
        mock_latexmk.assert_awaited_once_with(tmp_path / "main.tex", tmp_path)
        mock_tectonic.assert_not_awaited()

    async def test_falls_back_to_tectonic(self, tmp_path: Path) -> None:
        """When latexmk is absent but tectonic is available."""
        tex_file = tmp_path / "main.tex"
        tex_file.write_text(r"\documentclass{article}")
        expected = CompileResult(success=True, log="ok", pdf_bytes=b"%PDF")

        def _which(name: str) -> str | None:
            return "/usr/bin/tectonic" if name == "tectonic" else None

        with (
            patch("shutil.which", side_effect=_which),
            patch(
                "phiacta.extensions.compiled_content.compile._run_latexmk",
                new_callable=AsyncMock,
            ) as mock_latexmk,
            patch(
                "phiacta.extensions.compiled_content.compile._run_tectonic",
                new_callable=AsyncMock,
                return_value=expected,
            ) as mock_tectonic,
        ):
            result = await _compile_in_dir("main.tex", tmp_path)

        assert result is expected
        mock_latexmk.assert_not_awaited()
        mock_tectonic.assert_awaited_once_with(tmp_path / "main.tex", tmp_path)

    async def test_raises_when_no_compiler(self, tmp_path: Path) -> None:
        """When neither latexmk nor tectonic is available."""
        tex_file = tmp_path / "main.tex"
        tex_file.write_text(r"\documentclass{article}")

        with patch("shutil.which", return_value=None):
            with pytest.raises(FileNotFoundError, match="No LaTeX compiler found"):
                await _compile_in_dir("main.tex", tmp_path)
