# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.models.agent import Agent
from phiacta.models.bundle import Bundle
from phiacta.models.claim import Claim
from phiacta.models.relation import Relation
from phiacta.models.source import Source
from phiacta.repositories.agent_repository import AgentRepository
from phiacta.repositories.base import BaseRepository
from phiacta.repositories.bundle_repository import BundleRepository
from phiacta.repositories.claim_repository import ClaimRepository
from phiacta.repositories.relation_repository import RelationRepository
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
        assert callable(getattr(repo, "get_by_lineage", None))
        assert callable(getattr(repo, "get_latest_version", None))
        assert callable(getattr(repo, "list_claims", None))


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


class TestRelationRepositoryInstantiation:
    def test_relation_repository_sets_model(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = RelationRepository(mock_session)
        assert repo.model is Relation

    def test_relation_repository_has_custom_methods(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = RelationRepository(mock_session)
        assert callable(getattr(repo, "get_relations_for_claim", None))
        assert callable(getattr(repo, "get_relations_by_type", None))


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
