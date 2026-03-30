# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import uuid4

from phiacta.core.models.user import User
from phiacta.core.models.base import Base, TimestampMixin, UUIDMixin
from phiacta.core.models.entry import Entry
from phiacta.core.models.outbox import Outbox


class TestEntryDefaults:
    def test_entry_defaults(self) -> None:
        entry = Entry(repo_name=str(uuid4()), created_by=uuid4())
        assert entry.forgejo_repo_id is None
        assert entry.current_head_sha is None
        visibility_col = Entry.__table__.c["visibility"]
        assert visibility_col.default.arg == "public"

    def test_entry_has_no_removed_columns(self) -> None:
        cols = {c.name for c in Entry.__table__.columns}
        assert "title" not in cols
        assert "layout_hint" not in cols
        assert "content_cache" not in cols


class TestOutboxDefaults:
    def test_outbox_fields(self) -> None:
        entry = Outbox(aggregate_id=uuid4(), aggregate_type="entry", operation="create_repo", payload={})
        assert entry.operation == "create_repo"


class TestUserDefaults:
    def test_user_defaults(self) -> None:
        user = User(username="researcher", password_hash="$2b$12$fakehash")
        assert user.username == "researcher"


class TestUUIDMixin:
    def test_uuid_mixin(self) -> None:
        col = User.__table__.c["id"]
        assert col.primary_key is True


class TestTimestampMixin:
    def test_timestamp_fields_exist(self) -> None:
        table = Entry.__table__
        assert "created_at" in table.c
        assert "updated_at" in table.c

    def test_base_is_declarative(self) -> None:
        assert hasattr(Base, "metadata")
