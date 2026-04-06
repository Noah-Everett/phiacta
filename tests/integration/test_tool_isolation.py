# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Integration test: tool import isolation.

Tools must NOT import Entry models or DB sessions directly. They receive
service interfaces from extensions + EntryService. This test scans all
files under ``tools/`` for prohibited imports.

This is a static analysis test, not a runtime test.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


def _get_tools_dir() -> Path:
    """Return the absolute path to the tools directory."""
    this_file = Path(__file__).resolve()
    project_root = this_file.parent.parent.parent
    tools_dir = project_root / "src" / "phiacta" / "tools"
    return tools_dir


def _find_python_files(directory: Path) -> list[Path]:
    """Recursively find all .py files under a directory."""
    if not directory.exists():
        return []
    return sorted(directory.rglob("*.py"))


def _extract_imports(filepath: Path) -> list[str]:
    """Parse a Python file and extract all import module paths."""
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


_PROHIBITED_PATTERNS = [
    "phiacta.core.db",
    "phiacta.core.models",
]


def _is_prohibited_import(module_path: str) -> bool:
    """Check if a module path matches any prohibited pattern."""
    for pattern in _PROHIBITED_PATTERNS:
        if module_path == pattern or module_path.startswith(pattern + "."):
            return True
    # Also check for extension model imports: phiacta.extensions.*.models
    parts = module_path.split(".")
    if (
        len(parts) >= 4
        and parts[0] == "phiacta"
        and parts[1] == "extensions"
        and "models" in parts
    ):
        return True
    return False


class TestToolImportIsolation:
    """Static analysis: no file in tools/ imports from core.db, core.models,
    or extensions.*.models."""

    def test_no_prohibited_imports_in_tools(self) -> None:
        tools_dir = _get_tools_dir()
        if not tools_dir.exists():
            pytest.skip("tools/ directory not found")

        python_files = _find_python_files(tools_dir)
        if not python_files:
            pytest.skip("No Python files found in tools/")

        violations: list[str] = []
        for filepath in python_files:
            imports = _extract_imports(filepath)
            for imp in imports:
                if _is_prohibited_import(imp):
                    relative = filepath.relative_to(tools_dir.parent.parent.parent)
                    violations.append(f"{relative}: imports {imp}")

        if violations:
            msg = (
                "Tool isolation violation -- tools/ must not import from "
                "core.db, core.models, or extensions.*.models:\n"
                + "\n".join(f"  - {v}" for v in violations)
            )
            pytest.fail(msg)

    def test_tools_directory_exists(self) -> None:
        tools_dir = _get_tools_dir()
        assert tools_dir.exists(), f"Expected tools directory at {tools_dir}"

    def test_tools_has_python_files(self) -> None:
        tools_dir = _get_tools_dir()
        python_files = _find_python_files(tools_dir)
        assert python_files, f"No Python files found in {tools_dir}"

    def test_known_tool_modules_exist(self) -> None:
        tools_dir = _get_tools_dir()
        expected = ["search", "graph"]
        for module in expected:
            module_dir = tools_dir / module
            assert module_dir.exists(), f"Expected tool module {module} at {module_dir}"
