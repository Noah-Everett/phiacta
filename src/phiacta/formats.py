# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Shared format constants used by entry creation and webhook ingestion.

Maps content_format values to their corresponding file extensions for the
README file in each entry's git repository.
"""

from __future__ import annotations

FORMAT_EXTENSIONS: dict[str, str] = {
    "markdown": ".md",
    "latex": ".tex",
    "plain": ".txt",
}
