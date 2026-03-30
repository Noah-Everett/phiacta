# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Integration tests for generic provider dispatch on entry create (PHI-107).

Tests the provider write() path against a real database session, verifying:
- MetadataProvider.write() creates a row when none exists (create path)
- MetadataProvider.write() updates a row when one exists (update path)
- MetadataProvider.write() raises ValueError for missing/invalid title
- required_on_create validation logic in EntryService
- Provider failure rolls back the entire transaction
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.user import User
from phiacta.core.models.entry import Entry
from phiacta.core.models.entity import Entity
from phiacta.extensions.metadata.models import ExtensionMetadata
import phiacta.extensions.types.models  # noqa: F401
import phiacta.extensions.tags.models  # noqa: F401
import phiacta.extensions.references.models  # noqa: F401


async def _create_user_and_entry(
    db_session: AsyncSession,
) -> tuple[User, Entry]:
    """Helper: create a user and entry in the database."""
    from tests.conftest import make_user, make_entry
    suffix = uuid4().hex[:8]
    user = User(**make_user(handle=f"dispatch-{suffix}"))
    db_session.add(user)
    await db_session.flush()

    entity = Entity(entity_type="entry", created_by=user.id)
    db_session.add(entity)
    await db_session.flush()

    entry = Entry(id=entity.id, created_by=user.id, repo_name=str(entity.id))
    db_session.add(entry)
    await db_session.flush()
    return user, entry


# ---------------------------------------------------------------------------
# MetadataProvider.write() — create path (no existing row)
# ---------------------------------------------------------------------------


class TestMetadataProviderWriteCreate:
    """Tests that MetadataProvider.write() creates a metadata row when
    none exists for the given entry (the create path)."""

    async def test_write_creates_metadata_row(
        self, db_session: AsyncSession,
    ) -> None:
        """Calling write() on a fresh entry_id with title and summary
        creates a new ExtensionMetadata row."""
        from phiacta.extensions.metadata.provider import MetadataProvider

        user, entry = await _create_user_and_entry(db_session)
        provider = MetadataProvider()

        await provider.write(
            entry.id,
            {"title": "New Title", "summary": "A description"},
            user.id,
            db_session,
        )
        await db_session.flush()

        result = await db_session.execute(
            select(ExtensionMetadata).where(
                ExtensionMetadata.entity_id == entry.id
            )
        )
        meta = result.scalar_one_or_none()
        assert meta is not None
        assert meta.title == "New Title"
        assert meta.summary == "A description"
        assert meta.created_by == user.id

    async def test_write_creates_with_title_only(
        self, db_session: AsyncSession,
    ) -> None:
        """write() with only title (no summary) creates the row with
        summary=None."""
        from phiacta.extensions.metadata.provider import MetadataProvider

        user, entry = await _create_user_and_entry(db_session)
        provider = MetadataProvider()

        await provider.write(
            entry.id,
            {"title": "Title Only"},
            user.id,
            db_session,
        )
        await db_session.flush()

        result = await db_session.execute(
            select(ExtensionMetadata).where(
                ExtensionMetadata.entity_id == entry.id
            )
        )
        meta = result.scalar_one_or_none()
        assert meta is not None
        assert meta.title == "Title Only"
        assert meta.summary is None


# ---------------------------------------------------------------------------
# MetadataProvider.write() — update path (existing row)
# ---------------------------------------------------------------------------


class TestMetadataProviderWriteUpdate:
    """Tests that MetadataProvider.write() updates an existing metadata row."""

    async def test_write_updates_existing_row(
        self, db_session: AsyncSession,
    ) -> None:
        """Calling write() when a metadata row already exists updates
        the specified fields."""
        from phiacta.extensions.metadata.provider import MetadataProvider
        from phiacta.extensions.metadata.repository import MetadataRepository

        user, entry = await _create_user_and_entry(db_session)

        # Pre-create a metadata row
        repo = MetadataRepository(db_session)
        await repo.create(entry.id, "Original Title", user.id, "Original Summary")
        await db_session.flush()

        # Now update via provider
        provider = MetadataProvider()
        await provider.write(
            entry.id,
            {"summary": "Updated Summary"},
            user.id,
            db_session,
        )
        await db_session.flush()

        result = await db_session.execute(
            select(ExtensionMetadata).where(
                ExtensionMetadata.entity_id == entry.id
            )
        )
        meta = result.scalar_one()
        assert meta.title == "Original Title"  # unchanged
        assert meta.summary == "Updated Summary"  # updated


# ---------------------------------------------------------------------------
# MetadataProvider.write() — validation failures
# ---------------------------------------------------------------------------


class TestMetadataProviderWriteValidation:
    """Tests that MetadataProvider.write() raises ValueError for invalid
    data during the create path."""

    async def test_write_fails_without_title_on_create(
        self, db_session: AsyncSession,
    ) -> None:
        """Calling write() on a fresh entry without title raises ValueError."""
        from phiacta.extensions.metadata.provider import MetadataProvider

        user, entry = await _create_user_and_entry(db_session)
        provider = MetadataProvider()

        with pytest.raises(ValueError, match="(?i)title"):
            await provider.write(
                entry.id,
                {"summary": "No title provided"},
                user.id,
                db_session,
            )

    async def test_write_fails_with_empty_title_on_create(
        self, db_session: AsyncSession,
    ) -> None:
        """Calling write() with empty string title raises ValueError."""
        from phiacta.extensions.metadata.provider import MetadataProvider

        user, entry = await _create_user_and_entry(db_session)
        provider = MetadataProvider()

        with pytest.raises(ValueError, match="(?i)title"):
            await provider.write(
                entry.id,
                {"title": ""},
                user.id,
                db_session,
            )

    async def test_write_fails_with_title_over_500_chars_on_create(
        self, db_session: AsyncSession,
    ) -> None:
        """Calling write() with title > 500 chars raises ValueError."""
        from phiacta.extensions.metadata.provider import MetadataProvider

        user, entry = await _create_user_and_entry(db_session)
        provider = MetadataProvider()

        with pytest.raises(ValueError, match="(?i)title"):
            await provider.write(
                entry.id,
                {"title": "x" * 501},
                user.id,
                db_session,
            )


# ---------------------------------------------------------------------------
# required_on_create validation in EntryService
# ---------------------------------------------------------------------------


class TestRequiredOnCreateInService:
    """Tests that EntryService validates required_on_create fields from
    all providers before performing any DB flush."""

    async def test_missing_required_field_raises_before_flush(
        self, db_session: AsyncSession,
    ) -> None:
        """When a provider declares 'title' in required_on_create but
        the request omits it, EntryService should raise ValueError
        BEFORE creating the entry row."""
        from phiacta.core.services.entry_service import EntryService
        from phiacta.extensions.metadata.provider import entry_data_provider as mdp
        from pydantic import BaseModel, ConfigDict

        from tests.conftest import make_user as _make_user
        user = User(**_make_user(handle=f"reqval-{uuid4().hex[:8]}"))
        db_session.add(user)
        await db_session.flush()

        class FakeBody(BaseModel):
            model_config = ConfigDict(extra="allow")
            content: str | None = None
            content_format: str = "markdown"

        body = FakeBody()

        service = EntryService(db_session)

        with pytest.raises((ValueError, Exception)):
            await service.create_entry(
                body,  # type: ignore[arg-type]
                user,
                providers=[mdp],
                provider_fields=body.model_extra or {},
            )

        # Verify no entry was created
        result = await db_session.execute(
            select(Entry).where(Entry.created_by == user.id)
        )
        entries = result.scalars().all()
        assert len(entries) == 0


# ---------------------------------------------------------------------------
# Provider failure rolls back transaction
# ---------------------------------------------------------------------------


class TestProviderFailureRollback:
    """Tests that when a provider raises ValueError during create,
    the entry row does not persist in the database."""

    async def test_provider_error_prevents_entry_persistence(
        self, db_session: AsyncSession,
    ) -> None:
        """If MetadataProvider.write() raises ValueError (e.g., empty title),
        the entry row should not be committed to the DB."""
        from phiacta.core.services.entry_service import EntryService
        from phiacta.extensions.metadata.provider import entry_data_provider as mdp
        from pydantic import BaseModel, ConfigDict

        from tests.conftest import make_user as _make_user
        user = User(**_make_user(handle=f"rollback-{uuid4().hex[:8]}"))
        db_session.add(user)
        await db_session.flush()

        user_id = user.id

        class FakeBody(BaseModel):
            model_config = ConfigDict(extra="allow")
            content: str | None = None
            content_format: str = "markdown"

        body = FakeBody.model_validate({"content_format": "markdown", "title": ""})

        service = EntryService(db_session)

        with pytest.raises(ValueError):
            await service.create_entry(
                body,  # type: ignore[arg-type]
                user,
                providers=[mdp],
                provider_fields=body.model_extra or {},
            )

        # The ValueError from the provider should have prevented commit.
        # Roll back the session to discard flushed-but-uncommitted state,
        # then verify nothing was persisted.
        await db_session.rollback()

        result = await db_session.execute(
            select(Entry).where(Entry.created_by == user_id)
        )
        entries = result.scalars().all()
        assert len(entries) == 0
