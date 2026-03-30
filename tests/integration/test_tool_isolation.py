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


def _get_src_root() -> Path:
    """Return the absolute path to src/phiacta/."""
    this_file = Path(__file__).resolve()
    return this_file.parent.parent.parent / "src" / "phiacta"


def _extract_import_names(filepath: Path) -> list[tuple[str, list[str]]]:
    """Parse a Python file and return (module, [imported_names]) pairs.

    For ``from X import Y, Z`` returns ``(X, [Y, Z])``.
    For ``import X`` returns ``(X, [])``.
    """
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    results: list[tuple[str, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                results.append((alias.name, []))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names = [alias.name for alias in node.names]
                results.append((node.module, names))
    return results


class TestToolDepsExportsEverythingNeeded:
    """Verify tool_deps.py re-exports everything tools need."""

    def test_get_db_importable(self) -> None:
        from phiacta.core.tool_deps import get_db  # noqa: F401

    def test_get_optional_user_importable(self) -> None:
        from phiacta.core.tool_deps import get_optional_user  # noqa: F401

    def test_get_current_user_importable(self) -> None:
        from phiacta.core.tool_deps import get_current_user  # noqa: F401

    def test_entry_data_provider_importable(self) -> None:
        from phiacta.core.tool_deps import EntryDataProvider  # noqa: F401


class TestToolRoutersUseToolDeps:
    """Verify tool routers import get_db from tool_deps, not from core.db.session."""

    def test_search_router_imports_get_db_from_tool_deps(self) -> None:
        tools_dir = _get_tools_dir()
        router_file = tools_dir / "search" / "router.py"
        assert router_file.exists(), f"Expected {router_file}"

        imports = _extract_import_names(router_file)
        for module, names in imports:
            if "get_db" in names:
                assert module == "phiacta.core.tool_deps", (
                    f"search/router.py imports get_db from {module}, "
                    f"should use phiacta.core.tool_deps"
                )
                return
        pytest.fail("search/router.py does not import get_db at all")

    def test_graph_router_imports_get_db_from_tool_deps(self) -> None:
        tools_dir = _get_tools_dir()
        router_file = tools_dir / "graph" / "router.py"
        assert router_file.exists(), f"Expected {router_file}"

        imports = _extract_import_names(router_file)
        for module, names in imports:
            if "get_db" in names:
                assert module == "phiacta.core.tool_deps", (
                    f"graph/router.py imports get_db from {module}, "
                    f"should use phiacta.core.tool_deps"
                )
                return
        pytest.fail("graph/router.py does not import get_db at all")

    def test_no_tool_file_imports_get_db_from_core_db_session(self) -> None:
        """No tool file should import get_db from core.db.session."""
        tools_dir = _get_tools_dir()
        python_files = _find_python_files(tools_dir)
        violations: list[str] = []
        for filepath in python_files:
            imports = _extract_import_names(filepath)
            for module, names in imports:
                if module == "phiacta.core.db.session" and "get_db" in names:
                    relative = filepath.relative_to(tools_dir)
                    violations.append(str(relative))
        assert not violations, (
            f"Tool files import get_db from core.db.session: {violations}"
        )


class TestNoDirectEntryModelInTools:
    """Verify no tool file directly imports the Entry model."""

    def test_no_entry_model_import_in_tool_files(self) -> None:
        """Tool files should not import Entry from core.models.entry."""
        tools_dir = _get_tools_dir()
        python_files = _find_python_files(tools_dir)
        violations: list[str] = []
        for filepath in python_files:
            imports = _extract_import_names(filepath)
            for module, names in imports:
                if "Entry" in names and (
                    module.startswith("phiacta.core.models")
                ):
                    relative = filepath.relative_to(tools_dir)
                    violations.append(f"{relative}: from {module} import Entry")
        assert not violations, (
            "Tool files import Entry model directly:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


class TestServiceFilesExistInCorrectLocations:
    """Verify graph_query.py and search_service.py were moved to the correct locations."""

    def test_graph_query_exists_in_core_services(self) -> None:
        src_root = _get_src_root()
        graph_query = src_root / "core" / "services" / "graph_query.py"
        assert graph_query.exists(), (
            f"Expected graph_query.py at {graph_query} "
            f"(moved from tools/graph/repository.py)"
        )

    def test_search_service_exists_in_search_tsv_extension(self) -> None:
        src_root = _get_src_root()
        search_service = src_root / "extensions" / "search_tsv" / "search_service.py"
        assert search_service.exists(), (
            f"Expected search_service.py at {search_service} "
            f"(moved from tools/search/repository.py)"
        )


class TestOldToolRepositoryFilesDeleted:
    """Verify the old repository.py files in tools/ were removed."""

    def test_search_repository_deleted(self) -> None:
        tools_dir = _get_tools_dir()
        old_file = tools_dir / "search" / "repository.py"
        assert not old_file.exists(), (
            f"Old tools/search/repository.py still exists at {old_file}. "
            f"Search logic should be in extensions/search_tsv/search_service.py"
        )

    def test_graph_repository_deleted(self) -> None:
        tools_dir = _get_tools_dir()
        old_file = tools_dir / "graph" / "repository.py"
        assert not old_file.exists(), (
            f"Old tools/graph/repository.py still exists at {old_file}. "
            f"Graph logic should be in core/services/graph_query.py"
        )


class TestSearchTsvImportPath:
    """Verify search_tsv is importable from extensions, not views."""

    def test_search_tsv_importable_from_extensions(self) -> None:
        from phiacta.extensions.search_tsv import manifest  # noqa: F401
        assert manifest.name == "search_tsv"

    def test_views_search_tsv_raises_import_error(self) -> None:
        with pytest.raises(ImportError):
            import phiacta.views.search_tsv  # type: ignore[import-not-found]  # noqa: F401

    def test_views_directory_does_not_exist(self) -> None:
        src_root = _get_src_root()
        views_dir = src_root / "views"
        assert not views_dir.exists(), (
            f"views/ directory still exists at {views_dir}. "
            f"Views were merged into extensions in the platform overhaul."
        )
