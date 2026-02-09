# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NewPublishing Contributors

from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from newpublishing.models.agent import Agent
from newpublishing.models.bundle import Bundle
from newpublishing.models.claim import Claim
from newpublishing.models.edge import Edge
from newpublishing.models.source import Source
from newpublishing.repositories.agent_repository import AgentRepository
from newpublishing.repositories.base import BaseRepository
from newpublishing.repositories.bundle_repository import BundleRepository
from newpublishing.repositories.claim_repository import ClaimRepository
from newpublishing.repositories.edge_repository import EdgeRepository
from newpublishing.repositories.source_repository import SourceRepository


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


class TestEdgeRepositoryInstantiation:
    def test_edge_repository_sets_model(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = EdgeRepository(mock_session)
        assert repo.model is Edge

    def test_edge_repository_has_custom_methods(self) -> None:
        mock_session = MagicMock(spec=AsyncSession)
        repo = EdgeRepository(mock_session)
        assert callable(getattr(repo, "get_edges_for_claim", None))
        assert callable(getattr(repo, "get_edges_by_type", None))


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
