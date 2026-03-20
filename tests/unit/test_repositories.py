# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.agent import Agent
from phiacta.core.models.entry import Entry
from phiacta.core.models.entry_ref import EntryRef
from phiacta.core.repositories.agent_repository import AgentRepository
from phiacta.core.repositories.base import BaseRepository
from phiacta.core.repositories.entry_ref_repository import EntryRefRepository
from phiacta.core.repositories.entry_repository import EntryRepository


class TestBaseRepositoryInstantiation:
    def test_base_repository_stores_session_and_model(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = BaseRepository(mock_session, Entry)
        assert repo.session is mock_session
        assert repo.model is Entry


class TestEntryRepositoryInstantiation:
    def test_entry_repository_sets_model(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = EntryRepository(mock_session)
        assert repo.model is Entry

    def test_entry_repository_has_custom_methods(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = EntryRepository(mock_session)
        assert callable(getattr(repo, "list_entries", None))
        assert callable(getattr(repo, "count_entries", None))
        assert callable(getattr(repo, "update_repo_status", None))


class TestAgentRepositoryInstantiation:
    def test_agent_repository_sets_model(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = AgentRepository(mock_session)
        assert repo.model is Agent

    def test_agent_repository_has_custom_methods(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = AgentRepository(mock_session)
        assert callable(getattr(repo, "get_by_handle", None))
        assert callable(getattr(repo, "get_by_email", None))


class TestEntryRefRepositoryInstantiation:
    def test_entry_ref_repository_sets_model(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = EntryRefRepository(mock_session)
        assert repo.model is EntryRef

    def test_entry_ref_repository_has_custom_methods(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = EntryRefRepository(mock_session)
        assert callable(getattr(repo, "list_by_entry", None))
        assert callable(getattr(repo, "list_by_rel", None))
        assert callable(getattr(repo, "count_all", None))


class TestBaseRepositoryInheritance:
    def test_entry_repo_inherits_base_methods(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = EntryRepository(mock_session)
        assert callable(getattr(repo, "get_by_id", None))
        assert callable(getattr(repo, "create", None))
        assert callable(getattr(repo, "list_all", None))
        assert callable(getattr(repo, "delete", None))

    def test_agent_repo_inherits_base_methods(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = AgentRepository(mock_session)
        assert callable(getattr(repo, "get_by_id", None))
        assert callable(getattr(repo, "create", None))
        assert callable(getattr(repo, "list_all", None))
        assert callable(getattr(repo, "delete", None))
