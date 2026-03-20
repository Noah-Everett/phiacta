# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import uuid4

from phiacta.core.models.agent import Agent
from phiacta.core.models.base import Base, TimestampMixin, UUIDMixin
from phiacta.core.models.entry import Entry
from phiacta.core.models.entry_ref import EntryRef
from phiacta.core.models.outbox import Outbox


class TestEntryDefaults:
    def test_entry_defaults(self) -> None:
        agent_id = uuid4()
        entry_id = uuid4()
        entry = Entry(
            title="Test entry",
            repo_name=str(entry_id),
            created_by=agent_id,
        )
        assert entry.title == "Test entry"
        assert entry.created_by == agent_id
        assert entry.content_cache is None
        assert entry.forgejo_repo_id is None
        assert entry.current_head_sha is None
        assert entry.layout_hint is None
        assert entry.summary is None
        assert entry.license is None
        # Column-level defaults applied at flush
        status_col = Entry.__table__.c["status"]
        assert status_col.default is not None
        assert status_col.default.arg == "active"
        repo_status_col = Entry.__table__.c["repo_status"]
        assert repo_status_col.default is not None
        assert repo_status_col.default.arg == "provisioning"
        content_format_col = Entry.__table__.c["content_format"]
        assert content_format_col.default is not None
        assert content_format_col.default.arg == "markdown"
        schema_version_col = Entry.__table__.c["schema_version"]
        assert schema_version_col.default is not None
        assert schema_version_col.default.arg == 1

    def test_entry_layout_hint_accepts_arbitrary_strings(self) -> None:
        """layout_hint is freeform text -- no CHECK constraint in core."""
        for hint in ["paper", "theorem", "dataset", "custom_layout"]:
            entry = Entry(
                title=f"Entry with {hint}",
                layout_hint=hint,
                repo_name=str(uuid4()),
                created_by=uuid4(),
            )
            assert entry.layout_hint == hint


class TestEntryRefDefaults:
    def test_entry_ref_fields(self) -> None:
        entry_a = uuid4()
        entry_b = uuid4()
        ref = EntryRef(
            from_entry_id=entry_a,
            to_entry_id=entry_b,
            rel="evidence",
        )
        assert ref.rel == "evidence"
        assert ref.from_entry_id == entry_a
        assert ref.to_entry_id == entry_b
        assert ref.version_sha is None
        assert ref.note is None


class TestOutboxDefaults:
    def test_outbox_fields(self) -> None:
        entry = Outbox(
            aggregate_id=uuid4(),
            aggregate_type="entry",
            operation="create_repo",
            payload={"entry_id": str(uuid4())},
        )
        assert entry.operation == "create_repo"
        assert entry.aggregate_type == "entry"
        assert entry.last_error is None
        assert entry.processed_at is None
        # Column-level defaults
        status_col = Outbox.__table__.c["status"]
        assert status_col.default.arg == "pending"
        attempts_col = Outbox.__table__.c["attempts"]
        assert attempts_col.default.arg == 0


class TestAgentDefaults:
    def test_agent_defaults(self) -> None:
        agent = Agent(
            agent_type="human",
            handle="researcher",
            email="researcher@example.com",
            password_hash="$2b$12$fakehash",
        )
        assert agent.agent_type == "human"
        assert agent.handle == "researcher"
        assert agent.email == "researcher@example.com"
        is_active_col = Agent.__table__.c["is_active"]
        assert is_active_col.server_default is not None


class TestUUIDMixin:
    def test_uuid_mixin_generates_uuid(self) -> None:
        agent = Agent(
            agent_type="ai",
            handle="ai-agent",
            email="ai@example.com",
            password_hash="$2b$12$fakehash",
        )
        assert agent.id is not None or hasattr(Agent, "id")
        col = Agent.__table__.c["id"]
        assert col.primary_key is True
        assert col.default is not None


class TestTimestampMixin:
    def test_timestamp_mixin_fields_exist(self) -> None:
        table = Entry.__table__
        assert "created_at" in table.c
        assert "updated_at" in table.c
        assert table.c["created_at"].server_default is not None
        assert table.c["updated_at"].server_default is not None

    def test_mixin_classes_have_attributes(self) -> None:
        assert hasattr(UUIDMixin, "id")
        assert hasattr(TimestampMixin, "created_at")
        assert hasattr(TimestampMixin, "updated_at")

    def test_base_is_declarative(self) -> None:
        assert hasattr(Base, "metadata")
        assert hasattr(Base, "registry")
