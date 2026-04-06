# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for activity-related Pydantic schemas.

Tests serialization/deserialization of ActivityItem and the
activity feed response shape.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from phiacta.core.schemas.activity import ActivityFeedResponse, ActivityItem


class TestActivityItemSchema:
    """ActivityItem Pydantic schema validation."""

    def test_valid_activity_item(self) -> None:
        """A fully valid ActivityItem is accepted."""
        item = ActivityItem(
            id=uuid4(),
            actor_id=uuid4(),
            action="entry.created",
            entity_type="entry",
            entity_id=uuid4(),
            parent_id=None,
            metadata={"title": "Test Entry"},
            created_at=datetime.now(UTC),
        )
        assert item.action == "entry.created"
        assert item.entity_type == "entry"
        assert item.parent_id is None
        assert item.metadata == {"title": "Test Entry"}

    def test_activity_item_with_parent_id(self) -> None:
        """ActivityItem can have a non-null parent_id."""
        parent_id = uuid4()
        item = ActivityItem(
            id=uuid4(),
            actor_id=uuid4(),
            action="issue.created",
            entity_type="issue",
            entity_id=uuid4(),
            parent_id=parent_id,
            metadata={"title": "Bug report"},
            created_at=datetime.now(UTC),
        )
        assert item.parent_id == parent_id

    def test_activity_item_with_null_metadata(self) -> None:
        """ActivityItem metadata can be null."""
        item = ActivityItem(
            id=uuid4(),
            actor_id=uuid4(),
            action="entry.archived",
            entity_type="entry",
            entity_id=uuid4(),
            parent_id=None,
            metadata=None,
            created_at=datetime.now(UTC),
        )
        assert item.metadata is None

    def test_activity_item_requires_id(self) -> None:
        """Omitting 'id' raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ActivityItem(
                action="entry.created",
                entity_type="entry",
                entity_id=uuid4(),
                parent_id=None,
                metadata=None,
                created_at=datetime.now(UTC),
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("id",) for e in errors)

    def test_activity_item_requires_action(self) -> None:
        """Omitting 'action' raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ActivityItem(
                id=uuid4(),
                entity_type="entry",
                entity_id=uuid4(),
                parent_id=None,
                metadata=None,
                created_at=datetime.now(UTC),
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("action",) for e in errors)

    def test_activity_item_requires_entity_type(self) -> None:
        """Omitting 'entity_type' raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ActivityItem(
                id=uuid4(),
                actor_id=uuid4(),
                action="entry.created",
                entity_id=uuid4(),
                parent_id=None,
                metadata=None,
                created_at=datetime.now(UTC),
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("entity_type",) for e in errors)

    def test_activity_item_requires_entity_id(self) -> None:
        """Omitting 'entity_id' raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ActivityItem(
                id=uuid4(),
                actor_id=uuid4(),
                action="entry.created",
                entity_type="entry",
                parent_id=None,
                metadata=None,
                created_at=datetime.now(UTC),
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("entity_id",) for e in errors)

    def test_activity_item_requires_created_at(self) -> None:
        """Omitting 'created_at' raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ActivityItem(
                id=uuid4(),
                actor_id=uuid4(),
                action="entry.created",
                entity_type="entry",
                entity_id=uuid4(),
                parent_id=None,
                metadata=None,
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("created_at",) for e in errors)

    def test_activity_item_action_is_string(self) -> None:
        """Action field accepts any string (action vocabulary is enforced
        at the service layer, not the schema layer)."""
        item = ActivityItem(
            id=uuid4(),
            actor_id=uuid4(),
            action="custom.action",
            entity_type="entry",
            entity_id=uuid4(),
            parent_id=None,
            metadata=None,
            created_at=datetime.now(UTC),
        )
        assert item.action == "custom.action"

    def test_activity_item_serialization(self) -> None:
        """ActivityItem serializes to dict with correct field names."""
        item_id = uuid4()
        actor_id = uuid4()
        entity_id = uuid4()
        now = datetime.now(UTC)
        item = ActivityItem(
            id=item_id,
            actor_id=actor_id,
            action="entry.created",
            entity_type="entry",
            entity_id=entity_id,
            parent_id=None,
            metadata={"key": "value"},
            created_at=now,
        )
        serialized = item.model_dump(mode="json")
        assert serialized["id"] == str(item_id)
        assert serialized["action"] == "entry.created"
        assert serialized["entity_type"] == "entry"
        assert serialized["entity_id"] == str(entity_id)
        assert serialized["parent_id"] is None
        assert serialized["metadata"] == {"key": "value"}
        assert serialized["created_at"] is not None

    def test_all_known_actions_accepted(self) -> None:
        """All actions from the spec vocabulary are valid."""
        actions = [
            "entry.created",
            "entry.archived",
            "entry.unarchived",
            "issue.created",
            "issue.closed",
            "issue.commented",
            "edit.created",
            "edit.merged",
            "edit.closed",
        ]
        for action in actions:
            item = ActivityItem(
                id=uuid4(),
                actor_id=uuid4(),
                action=action,
                entity_type="entry",
                entity_id=uuid4(),
                parent_id=None,
                metadata=None,
                created_at=datetime.now(UTC),
            )
            assert item.action == action

    def test_all_known_entity_types_accepted(self) -> None:
        """All entity types from the spec are valid."""
        entity_types = ["user", "entry", "issue", "edit", "comment"]
        for et in entity_types:
            item = ActivityItem(
                id=uuid4(),
                actor_id=uuid4(),
                action="entry.created",
                entity_type=et,
                entity_id=uuid4(),
                parent_id=None,
                metadata=None,
                created_at=datetime.now(UTC),
            )
            assert item.entity_type == et


class TestActivityFeedResponseSchema:
    """ActivityFeedResponse schema validation."""

    def test_valid_response_with_items(self) -> None:
        """A response with items and a cursor is accepted."""
        items = [
            ActivityItem(
                id=uuid4(),
                actor_id=uuid4(),
                action="entry.created",
                entity_type="entry",
                entity_id=uuid4(),
                parent_id=None,
                metadata=None,
                created_at=datetime.now(UTC),
            )
        ]
        cursor = uuid4()
        response = ActivityFeedResponse(items=items, next_cursor=cursor)
        assert len(response.items) == 1
        assert response.next_cursor == cursor

    def test_valid_response_empty_items(self) -> None:
        """An empty response with null cursor is accepted."""
        response = ActivityFeedResponse(items=[], next_cursor=None)
        assert response.items == []
        assert response.next_cursor is None

    def test_response_requires_items(self) -> None:
        """Omitting 'items' raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ActivityFeedResponse(next_cursor=None)
        errors = exc_info.value.errors()
        assert any("items" in str(e["loc"]) for e in errors)

    def test_response_serialization(self) -> None:
        """ActivityFeedResponse serializes correctly to JSON-compatible dict."""
        item = ActivityItem(
            id=uuid4(),
            actor_id=uuid4(),
            action="entry.created",
            entity_type="entry",
            entity_id=uuid4(),
            parent_id=None,
            metadata={"title": "Test"},
            created_at=datetime.now(UTC),
        )
        cursor = uuid4()
        response = ActivityFeedResponse(items=[item], next_cursor=cursor)
        serialized = response.model_dump(mode="json")
        assert "items" in serialized
        assert "next_cursor" in serialized
        assert len(serialized["items"]) == 1
        assert serialized["next_cursor"] == str(cursor)

    def test_response_null_cursor_serialization(self) -> None:
        """null next_cursor serializes as None/null."""
        response = ActivityFeedResponse(items=[], next_cursor=None)
        serialized = response.model_dump(mode="json")
        assert serialized["next_cursor"] is None

    def test_response_with_multiple_items(self) -> None:
        """Response with multiple items preserves order."""
        items = []
        for i in range(5):
            items.append(ActivityItem(
                id=uuid4(),
                actor_id=uuid4(),
                action="entry.created",
                entity_type="entry",
                entity_id=uuid4(),
                parent_id=None,
                metadata=None,
                created_at=datetime.now(UTC),
            ))
        response = ActivityFeedResponse(items=items, next_cursor=uuid4())
        assert len(response.items) == 5

    def test_response_items_are_activity_items(self) -> None:
        """Items in the response are ActivityItem instances."""
        item = ActivityItem(
            id=uuid4(),
            actor_id=uuid4(),
            action="entry.created",
            entity_type="entry",
            entity_id=uuid4(),
            parent_id=None,
            metadata=None,
            created_at=datetime.now(UTC),
        )
        response = ActivityFeedResponse(items=[item], next_cursor=None)
        assert isinstance(response.items[0], ActivityItem)
        assert response.items[0].action == "entry.created"
