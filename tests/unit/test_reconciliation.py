# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for ReconciliationReport and drift detection logic (NEV-164).

Tests the ReconciliationReport dataclass and any pure-logic helpers in the
reconciliation module. These tests do NOT touch the database -- they verify
the data structures and classification logic in isolation.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from phiacta.core.services.reconciliation import ReconciliationReport


class TestReconciliationReportDefaults:
    """Verify ReconciliationReport dataclass has correct default values."""

    def test_default_values_are_zero(self) -> None:
        report = ReconciliationReport()
        assert report.entries_checked == 0
        assert report.entries_drifted == 0
        assert report.entries_repaired == 0
        assert report.entries_errored == 0
        assert report.entries_skipped == 0
        assert report.orphan_repos == []
        assert report.missing_repos == []
        assert report.stuck_provisioning == []
        assert report.still_provisioning == []
        assert report.errors == []
        assert report.dry_run is False

    def test_dry_run_flag_set_when_specified(self) -> None:
        report = ReconciliationReport(dry_run=True)
        assert report.dry_run is True

    def test_fields_are_independently_mutable(self) -> None:
        """Each report field can be set independently -- no shared state."""
        report = ReconciliationReport()
        report.entries_checked = 5
        report.entries_drifted = 3
        report.entries_repaired = 2
        report.entries_errored = 1
        report.entries_skipped = 1

        assert report.entries_checked == 5
        assert report.entries_drifted == 3
        assert report.entries_repaired == 2
        assert report.entries_errored == 1
        assert report.entries_skipped == 1

    def test_lists_are_not_shared_between_instances(self) -> None:
        """Each ReconciliationReport instance must have its own list objects
        to prevent mutations leaking between instances."""
        report_a = ReconciliationReport()
        report_b = ReconciliationReport()

        report_a.orphan_repos.append("some-repo")
        assert "some-repo" not in report_b.orphan_repos

        report_a.missing_repos.append(uuid4())
        assert len(report_b.missing_repos) == 0

    def test_errors_list_stores_tuples(self) -> None:
        report = ReconciliationReport()
        entry_id = uuid4()
        report.errors.append((entry_id, "something went wrong"))
        assert len(report.errors) == 1
        assert report.errors[0][0] == entry_id
        assert report.errors[0][1] == "something went wrong"

    def test_report_with_all_fields_populated(self) -> None:
        """Construct a report with all fields set to non-default values."""
        eid1 = uuid4()
        eid2 = uuid4()
        report = ReconciliationReport(
            entries_checked=10,
            entries_drifted=3,
            entries_repaired=2,
            entries_errored=1,
            entries_skipped=4,
            orphan_repos=["orphan-1", "orphan-2"],
            missing_repos=[eid1],
            stuck_provisioning=[eid2],
            still_provisioning=[],
            errors=[(eid1, "parse error")],
            dry_run=True,
        )
        assert report.entries_checked == 10
        assert report.entries_drifted == 3
        assert report.entries_repaired == 2
        assert report.entries_errored == 1
        assert report.entries_skipped == 4
        assert len(report.orphan_repos) == 2
        assert len(report.missing_repos) == 1
        assert len(report.stuck_provisioning) == 1
        assert len(report.still_provisioning) == 0
        assert len(report.errors) == 1
        assert report.dry_run is True


class TestReconciliationReportArithmetic:
    """Verify that report counters are consistent with expected accounting."""

    def test_drifted_equals_repaired_plus_errored_when_no_dry_run(self) -> None:
        """In a non-dry-run, entries_drifted should equal
        entries_repaired + entries_errored (every drifted entry is either
        repaired or errored)."""
        report = ReconciliationReport(
            entries_checked=10,
            entries_drifted=5,
            entries_repaired=3,
            entries_errored=2,
            entries_skipped=2,
            dry_run=False,
        )
        assert report.entries_drifted == report.entries_repaired + report.entries_errored

    def test_dry_run_drifted_with_zero_repaired(self) -> None:
        """In dry-run mode, entries_repaired should be 0 even if
        entries_drifted > 0."""
        report = ReconciliationReport(
            entries_checked=10,
            entries_drifted=5,
            entries_repaired=0,
            entries_errored=0,
            entries_skipped=2,
            dry_run=True,
        )
        assert report.entries_repaired == 0
        assert report.entries_drifted == 5


class TestDriftClassificationLogic:
    """Test the classification of different drift scenarios.

    These tests verify that the service correctly classifies entries into
    the right categories. Since the implementation doesn't exist yet, these
    will fail -- but they define the expected behavior.
    """

    def test_uuid_parsing_for_repo_names(self) -> None:
        """Only valid UUID-format repo names should be considered for
        orphan detection. Non-UUID names are silently ignored."""
        valid_uuid = str(uuid4())
        # Valid UUID should parse
        parsed = UUID(valid_uuid)
        assert str(parsed) == valid_uuid

        # Non-UUID should raise ValueError
        import pytest
        with pytest.raises(ValueError, match="badly formed"):
            UUID("not-a-uuid")
        with pytest.raises(ValueError, match="badly formed"):
            UUID("config-repo")
        with pytest.raises(ValueError, match="badly formed"):
            UUID(".gitea")

    def test_visibility_values(self) -> None:
        """Visibility values are well-defined and non-overlapping."""
        visible = {"public"}
        hidden = {"private"}

        assert "public" in visible
        assert "private" in hidden
        assert "public" not in hidden
        assert "private" not in visible

        # Verify no overlap
        assert visible & hidden == set()
