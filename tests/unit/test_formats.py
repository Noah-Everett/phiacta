# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for FORMAT_EXTENSIONS constant (NEV-119).

Tests the shared format-to-extension mapping used by entry creation
and webhook ingestion to determine the README filename.
"""

from __future__ import annotations

from phiacta.formats import FORMAT_EXTENSIONS


class TestFormatExtensions:
    """Tests for the FORMAT_EXTENSIONS mapping."""

    def test_markdown_maps_to_md(self) -> None:
        """markdown format maps to .md extension."""
        assert FORMAT_EXTENSIONS["markdown"] == ".md"

    def test_latex_maps_to_tex(self) -> None:
        """latex format maps to .tex extension."""
        assert FORMAT_EXTENSIONS["latex"] == ".tex"

    def test_plain_maps_to_txt(self) -> None:
        """plain format maps to .txt extension."""
        assert FORMAT_EXTENSIONS["plain"] == ".txt"

    def test_contains_exactly_three_formats(self) -> None:
        """Only markdown, latex, and plain are in the mapping."""
        assert set(FORMAT_EXTENSIONS.keys()) == {"markdown", "latex", "plain"}

    def test_all_extensions_start_with_dot(self) -> None:
        """All file extensions start with a dot."""
        assert len(FORMAT_EXTENSIONS) > 0, "FORMAT_EXTENSIONS must not be empty"
        for ext in FORMAT_EXTENSIONS.values():
            assert ext.startswith("."), f"Extension {ext!r} does not start with '.'"
