# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for entry edit proposal Pydantic schemas (NEV-126, NEV-162).

Tests validate the EditProposalCreate schema's validation rules:
- title: required, max 500 chars
- body: optional, max 10000 chars
- files: required, at least one file change
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from phiacta.schemas.entry_edit import EditProposalCreate


class TestEditProposalCreateValidTitle:
    """Title field validation."""

    def test_valid_short_title(self) -> None:
        """A short title is accepted."""
        model = EditProposalCreate(
            title="Fix typo",
            files=[{"path": "README.md", "content": "dGVzdA=="}],
        )
        assert model.title == "Fix typo"

    def test_valid_title_at_max_length(self) -> None:
        """A title of exactly 500 characters is accepted."""
        title = "X" * 500
        model = EditProposalCreate(
            title=title,
            files=[{"path": "README.md", "content": "dGVzdA=="}],
        )
        assert len(model.title) == 500

    def test_title_exceeding_max_length_rejected(self) -> None:
        """A title of 501 characters is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            EditProposalCreate(
                title="X" * 501,
                files=[{"path": "README.md", "content": "dGVzdA=="}],
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("title",) for e in errors)

    def test_title_required(self) -> None:
        """Omitting the title field raises a ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            EditProposalCreate(
                files=[{"path": "README.md", "content": "dGVzdA=="}],
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("title",) for e in errors)

    def test_title_empty_string(self) -> None:
        """An empty title string is accepted by Pydantic (business logic may reject it)."""
        # Pydantic does not add min_length=1 by default, so empty is valid at schema level.
        # The API endpoint may add additional checks.
        model = EditProposalCreate(
            title="",
            files=[{"path": "README.md", "content": "dGVzdA=="}],
        )
        assert model.title == ""

    def test_title_with_unicode(self) -> None:
        """A title with unicode characters is accepted."""
        model = EditProposalCreate(
            title="Korrektur der Hypothese",
            files=[{"path": "README.md", "content": "dGVzdA=="}],
        )
        assert model.title == "Korrektur der Hypothese"

    def test_title_with_special_characters(self) -> None:
        """A title with special characters like slashes and brackets is accepted."""
        model = EditProposalCreate(
            title="Fix [issue #42]: path/to/file",
            files=[{"path": "README.md", "content": "dGVzdA=="}],
        )
        assert model.title == "Fix [issue #42]: path/to/file"


class TestEditProposalCreateValidBody:
    """Body field validation."""

    def test_body_is_optional(self) -> None:
        """Omitting the body field is valid (defaults to None)."""
        model = EditProposalCreate(
            title="No body",
            files=[{"path": "README.md", "content": "dGVzdA=="}],
        )
        assert model.body is None

    def test_body_explicit_none(self) -> None:
        """Setting body to None explicitly is valid."""
        model = EditProposalCreate(
            title="None body",
            body=None,
            files=[{"path": "README.md", "content": "dGVzdA=="}],
        )
        assert model.body is None

    def test_body_at_max_length(self) -> None:
        """A body of exactly 10000 characters is accepted."""
        body = "Y" * 10000
        model = EditProposalCreate(
            title="Long body",
            body=body,
            files=[{"path": "README.md", "content": "dGVzdA=="}],
        )
        assert len(model.body) == 10000

    def test_body_exceeding_max_length_rejected(self) -> None:
        """A body of 10001 characters is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            EditProposalCreate(
                title="Too long body",
                body="Y" * 10001,
                files=[{"path": "README.md", "content": "dGVzdA=="}],
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("body",) for e in errors)

    def test_body_empty_string(self) -> None:
        """An empty body string is accepted."""
        model = EditProposalCreate(
            title="Empty body",
            body="",
            files=[{"path": "README.md", "content": "dGVzdA=="}],
        )
        assert model.body == ""


class TestEditProposalCreateValidFiles:
    """Files field validation."""

    def test_files_required(self) -> None:
        """Omitting the files field raises a ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            EditProposalCreate(
                title="No files",
            )
        errors = exc_info.value.errors()
        assert any("files" in str(e["loc"]) for e in errors)

    def test_files_empty_list_rejected(self) -> None:
        """An empty files list is rejected (min_length=1)."""
        with pytest.raises(ValidationError) as exc_info:
            EditProposalCreate(
                title="Empty files",
                files=[],
            )
        errors = exc_info.value.errors()
        assert any("files" in str(e["loc"]) for e in errors)

    def test_files_single_file(self) -> None:
        """A single file change is accepted."""
        model = EditProposalCreate(
            title="Single file",
            files=[{"path": "README.md", "content": "dGVzdA=="}],
        )
        assert len(model.files) == 1
        assert model.files[0].path == "README.md"
        assert model.files[0].content == "dGVzdA=="

    def test_files_multiple_files(self) -> None:
        """Multiple file changes are accepted."""
        model = EditProposalCreate(
            title="Multiple files",
            files=[
                {"path": "README.md", "content": "dGVzdA=="},
                {"path": "data.csv", "content": "YSxiLGM="},
                {"path": "analysis.py", "content": "cHJpbnQoJ2hlbGxvJyk="},
            ],
        )
        assert len(model.files) == 3
        paths = [f.path for f in model.files]
        assert "README.md" in paths
        assert "data.csv" in paths
        assert "analysis.py" in paths

    def test_file_missing_path_rejected(self) -> None:
        """A file change without a path field is rejected."""
        with pytest.raises(ValidationError):
            EditProposalCreate(
                title="Missing path",
                files=[{"content": "dGVzdA=="}],
            )

    def test_file_missing_content_rejected(self) -> None:
        """A file change without a content field is rejected."""
        with pytest.raises(ValidationError):
            EditProposalCreate(
                title="Missing content",
                files=[{"path": "README.md"}],
            )

    def test_file_nested_path(self) -> None:
        """A file with a nested path like 'data/results.csv' is accepted."""
        model = EditProposalCreate(
            title="Nested path",
            files=[{"path": "data/results.csv", "content": "eCx5"}],
        )
        assert model.files[0].path == "data/results.csv"


class TestEditProposalCreateCombined:
    """Combined validation scenarios."""

    def test_full_valid_request(self) -> None:
        """A fully valid request with all fields is accepted."""
        model = EditProposalCreate(
            title="Full proposal",
            body="This proposal fixes several issues with the methodology section.",
            files=[
                {"path": "methodology.md", "content": "dGVzdA=="},
                {"path": "references.bib", "content": "QGFydGljbGU="},
            ],
        )
        assert model.title == "Full proposal"
        assert model.body is not None
        assert len(model.files) == 2

    def test_title_too_long_with_valid_files_still_rejected(self) -> None:
        """Even with valid files, a title exceeding the max is rejected."""
        with pytest.raises(ValidationError):
            EditProposalCreate(
                title="X" * 501,
                files=[{"path": "README.md", "content": "dGVzdA=="}],
            )

    def test_body_too_long_with_valid_title_and_files_still_rejected(self) -> None:
        """Even with valid title and files, a body exceeding the max is rejected."""
        with pytest.raises(ValidationError):
            EditProposalCreate(
                title="Valid title",
                body="Y" * 10001,
                files=[{"path": "README.md", "content": "dGVzdA=="}],
            )
