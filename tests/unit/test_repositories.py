# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.models.agent import Agent
from phiacta.models.bundle import Bundle
from phiacta.models.claim import Claim
from phiacta.models.reference import Reference
from phiacta.models.source import Source
from phiacta.repositories.agent_repository import AgentRepository
from phiacta.repositories.base import BaseRepository
from phiacta.repositories.bundle_repository import BundleRepository
from phiacta.repositories.claim_repository import ClaimRepository
from phiacta.repositories.interaction_repository import InteractionRepository
from phiacta.repositories.reference_repository import ReferenceRepository
from phiacta.repositories.source_repository import SourceRepository


class TestBaseRepositoryInstantiation:
    def test_base_repository_stores_session_and_model(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = BaseRepository(mock_session, Claim)
        assert repo.session is mock_session
        assert repo.model is Claim


class TestClaimRepositoryInstantiation:
    def test_claim_repository_sets_model(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = ClaimRepository(mock_session)
        assert repo.model is Claim

    def test_claim_repository_has_custom_methods(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = ClaimRepository(mock_session)
        assert callable(getattr(repo, "list_claims", None))
        assert callable(getattr(repo, "count_claims", None))
        assert callable(getattr(repo, "update_repo_status", None))


class TestAgentRepositoryInstantiation:
    def test_agent_repository_sets_model(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = AgentRepository(mock_session)
        assert repo.model is Agent

    def test_agent_repository_has_custom_methods(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = AgentRepository(mock_session)
        assert callable(getattr(repo, "get_by_external_id", None))
        assert callable(getattr(repo, "get_by_name", None))


class TestBundleRepositoryInstantiation:
    def test_bundle_repository_sets_model(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = BundleRepository(mock_session)
        assert repo.model is Bundle

    def test_bundle_repository_has_custom_methods(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = BundleRepository(mock_session)
        assert callable(getattr(repo, "get_by_idempotency_key", None))


class TestReferenceRepositoryInstantiation:
    def test_reference_repository_sets_model(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = ReferenceRepository(mock_session)
        assert repo.model is Reference

    def test_reference_repository_has_custom_methods(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = ReferenceRepository(mock_session)
        assert callable(getattr(repo, "list_by_source_uri", None))
        assert callable(getattr(repo, "list_by_target_uri", None))
        assert callable(getattr(repo, "list_by_claim", None))
        assert callable(getattr(repo, "list_by_role", None))


class TestInteractionRepositoryInstantiation:
    def test_interaction_repository_has_custom_methods(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = InteractionRepository(mock_session)
        assert callable(getattr(repo, "list_by_claim", None))
        assert callable(getattr(repo, "get_signal_by_agent", None))
        assert callable(getattr(repo, "get_with_author", None))
        assert callable(getattr(repo, "soft_delete", None))


class TestSourceRepositoryInstantiation:
    def test_source_repository_sets_model(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = SourceRepository(mock_session)
        assert repo.model is Source

    def test_source_repository_has_custom_methods(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = SourceRepository(mock_session)
        assert callable(getattr(repo, "get_by_external_ref", None))
        assert callable(getattr(repo, "get_by_content_hash", None))


class TestBaseRepositoryInheritance:
    def test_claim_repo_inherits_base_methods(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = ClaimRepository(mock_session)
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
