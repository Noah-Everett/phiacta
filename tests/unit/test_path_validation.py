# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for file path validation logic (NEV-124).

Tests both ``validate_file_path`` (write operations) and
``validate_file_path_read`` (read operations). Write validation blocks
``.phiacta/entry.yaml``; read validation allows all paths.
Both block traversal attacks and absolute paths.
"""

from __future__ import annotations

import pytest

from phiacta.core.api.entry_files import validate_file_path, validate_file_path_read


class TestValidateFilePathAcceptsValidPaths:
    """Valid paths must pass validation without raising."""

    def test_simple_filename(self) -> None:
        """A simple filename like 'README.md' is valid."""
        validate_file_path("README.md")

    def test_nested_path(self) -> None:
        """A nested path like 'subdir/file.txt' is valid."""
        validate_file_path("subdir/file.txt")

    def test_deeply_nested_path(self) -> None:
        """A deeply nested path like 'a/b/c.txt' is valid."""
        validate_file_path("a/b/c.txt")

    def test_file_with_spaces(self) -> None:
        """A path with spaces like 'file with spaces.md' is valid."""
        validate_file_path("file with spaces.md")

    def test_dotfile_not_phiacta(self) -> None:
        """A dotfile that is not .phiacta is valid."""
        validate_file_path(".gitignore")

    def test_dot_in_directory_name(self) -> None:
        """A directory with a dot like 'src.bak/file.txt' is valid."""
        validate_file_path("src.bak/file.txt")

    def test_phiacta_prefix_but_different_name(self) -> None:
        """'.phiacta_backup' is not '.phiacta' and should be allowed."""
        validate_file_path(".phiacta_backup/file.txt")

    def test_phiactax_directory(self) -> None:
        """'.phiactax/foo' is not '.phiacta' and should be allowed."""
        validate_file_path(".phiactax/foo")

    def test_single_character_filename(self) -> None:
        """A single character filename is valid."""
        validate_file_path("x")

    def test_filename_with_multiple_dots(self) -> None:
        """A filename like 'archive.tar.gz' is valid."""
        validate_file_path("archive.tar.gz")

    def test_path_containing_phiacta_substring(self) -> None:
        """A path that contains 'phiacta' as a substring elsewhere is valid."""
        validate_file_path("docs/about-phiacta.md")

    def test_path_with_phiacta_in_nested_dir(self) -> None:
        """A path like 'src/.phiacta_config/settings.yaml' is allowed."""
        validate_file_path("src/.phiacta_config/settings.yaml")


class TestValidateFilePathRejectsTraversal:
    """Paths containing '..' segments must be rejected."""

    def test_leading_dotdot(self) -> None:
        """'../etc/passwd' must be rejected."""
        with pytest.raises(ValueError, match="[Ii]nvalid file path"):
            validate_file_path("../etc/passwd")

    def test_dotdot_only(self) -> None:
        """'..' alone must be rejected."""
        with pytest.raises(ValueError, match="[Ii]nvalid file path"):
            validate_file_path("..")

    def test_middle_dotdot(self) -> None:
        """'foo/../bar' must be rejected."""
        with pytest.raises(ValueError, match="[Ii]nvalid file path"):
            validate_file_path("foo/../bar")

    def test_trailing_dotdot(self) -> None:
        """'foo/..' must be rejected."""
        with pytest.raises(ValueError, match="[Ii]nvalid file path"):
            validate_file_path("foo/..")

    def test_multiple_dotdot_segments(self) -> None:
        """'a/../../b' must be rejected."""
        with pytest.raises(ValueError, match="[Ii]nvalid file path"):
            validate_file_path("a/../../b")

    def test_dotdot_with_trailing_slash(self) -> None:
        """'../foo/' must be rejected."""
        with pytest.raises(ValueError, match="[Ii]nvalid file path"):
            validate_file_path("../foo/")


class TestValidateFilePathRejectsAbsolutePaths:
    """Paths starting with '/' must be rejected."""

    def test_absolute_unix_path(self) -> None:
        """'/etc/passwd' must be rejected."""
        with pytest.raises(ValueError, match="[Ii]nvalid file path"):
            validate_file_path("/etc/passwd")

    def test_absolute_single_slash(self) -> None:
        """'/' alone must be rejected."""
        with pytest.raises(ValueError, match="[Ii]nvalid file path"):
            validate_file_path("/")

    def test_absolute_nested(self) -> None:
        """'/a/b/c' must be rejected."""
        with pytest.raises(ValueError, match="[Ii]nvalid file path"):
            validate_file_path("/a/b/c")


class TestValidateFilePathRejectsPhiacta:
    """All .phiacta/* paths are writable (entry.yaml is no longer used)."""

    def test_phiacta_entry_yaml_is_allowed(self) -> None:
        """'.phiacta/entry.yaml' is writable (no longer generated or used)."""
        validate_file_path(".phiacta/entry.yaml")

    def test_phiacta_exact_is_allowed(self) -> None:
        """'.phiacta' alone is allowed (not a file, but not blocked)."""
        validate_file_path(".phiacta")

    def test_phiacta_content_md_is_allowed(self) -> None:
        """'.phiacta/content.md' is writable."""
        validate_file_path(".phiacta/content.md")

    def test_phiacta_refs_yaml_is_allowed(self) -> None:
        """'.phiacta/refs.yaml' is writable."""
        validate_file_path(".phiacta/refs.yaml")

    def test_phiacta_artifacts_manifest_is_allowed(self) -> None:
        """'.phiacta/artifacts/manifest.yaml' is writable."""
        validate_file_path(".phiacta/artifacts/manifest.yaml")


class TestValidateFilePathAllowsPhiactaSimilarNames:
    """Names similar to but not exactly .phiacta must be allowed."""

    def test_phiacta_backup(self) -> None:
        """'.phiacta_backup' must be allowed."""
        # Should not raise
        validate_file_path(".phiacta_backup")

    def test_phiactax(self) -> None:
        """'.phiactax/foo' must be allowed."""
        validate_file_path(".phiactax/foo")

    def test_dot_phiactas(self) -> None:
        """'.phiactas/file' must be allowed (extra 's')."""
        validate_file_path(".phiactas/file")

    def test_phiacta_no_dot(self) -> None:
        """'phiacta/file' (no leading dot) must be allowed."""
        validate_file_path("phiacta/file")


class TestValidateFilePathEdgeCases:
    """Edge cases for path validation."""

    def test_empty_string_is_rejected(self) -> None:
        """An empty path string must be rejected."""
        with pytest.raises(ValueError):
            validate_file_path("")

    def test_single_dot_is_accepted(self) -> None:
        """Path '.' is accepted (not '..' so not traversal)."""
        validate_file_path(".")

    def test_url_decoded_dotdot(self) -> None:
        """A path with URL-decoded '..' components must still be caught."""
        # This tests that the validation is applied AFTER URL decoding
        with pytest.raises(ValueError, match="[Ii]nvalid file path"):
            validate_file_path("foo/../bar")

    def test_phiacta_entry_yaml_edge_case(self) -> None:
        """'.phiacta/entry.yaml' is writable (no longer protected)."""
        validate_file_path(".phiacta/entry.yaml")


# ---------------------------------------------------------------------------
# validate_file_path_read — read validator (all paths readable)
# ---------------------------------------------------------------------------


class TestValidateFilePathReadAllowsAllPaths:
    """Read validation allows all paths including .phiacta/entry.yaml."""

    def test_normal_file(self) -> None:
        validate_file_path_read("README.md")

    def test_nested_path(self) -> None:
        validate_file_path_read("data/results/output.csv")

    def test_phiacta_entry_yaml_is_readable(self) -> None:
        """The identity file is readable even though it's write-blocked."""
        validate_file_path_read(".phiacta/entry.yaml")

    def test_phiacta_content_md_is_readable(self) -> None:
        validate_file_path_read(".phiacta/content.md")

    def test_phiacta_bare_is_readable(self) -> None:
        validate_file_path_read(".phiacta")

    def test_phiacta_refs_is_readable(self) -> None:
        validate_file_path_read(".phiacta/refs.yaml")


class TestValidateFilePathReadBlocksTraversal:
    """Read validation still blocks traversal and absolute paths."""

    def test_dotdot_blocked(self) -> None:
        with pytest.raises(ValueError, match="[Ii]nvalid file path"):
            validate_file_path_read("../etc/passwd")

    def test_middle_dotdot_blocked(self) -> None:
        with pytest.raises(ValueError, match="[Ii]nvalid file path"):
            validate_file_path_read("data/../../../etc/passwd")

    def test_absolute_path_blocked(self) -> None:
        with pytest.raises(ValueError, match="[Ii]nvalid file path"):
            validate_file_path_read("/etc/passwd")

    def test_empty_string_blocked(self) -> None:
        with pytest.raises(ValueError):
            validate_file_path_read("")
