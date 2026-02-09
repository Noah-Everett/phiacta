# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NewPublishing Contributors

from __future__ import annotations

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from newpublishing.models.agent import Agent
from newpublishing.models.claim import Claim
from newpublishing.models.edge import Edge, EdgeType
from newpublishing.models.namespace import Namespace
from newpublishing.repositories.edge_repository import EdgeRepository
from tests.conftest import make_agent, make_claim, make_edge, make_namespace

needs_db = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="TEST_DATABASE_URL not set; skipping integration test",
)


async def _setup_claims(
    db_session: AsyncSession,
) -> tuple[Agent, Namespace, Claim, Claim]:
    """Create prerequisite agent, namespace, and two claims."""
    agent = Agent(**make_agent())
    ns = Namespace(**make_namespace())
    db_session.add(agent)
    db_session.add(ns)
    await db_session.flush()

    claim_a = Claim(**make_claim(namespace_id=ns.id, created_by=agent.id, content="Claim A"))
    claim_b = Claim(**make_claim(namespace_id=ns.id, created_by=agent.id, content="Claim B"))
    db_session.add(claim_a)
    db_session.add(claim_b)
    await db_session.flush()
    return agent, ns, claim_a, claim_b


async def _ensure_edge_type(db_session: AsyncSession, name: str) -> None:
    """Insert an edge type if it does not already exist."""
    existing = await db_session.get(EdgeType, name)
    if existing is None:
        et = EdgeType(
            name=name,
            description=f"{name} relationship",
            category="evidential",
        )
        db_session.add(et)
        await db_session.flush()


@needs_db
class TestCreateAndGetEdge:
    async def test_create_and_get_edge(self, db_session: AsyncSession) -> None:
        agent, _ns, claim_a, claim_b = await _setup_claims(db_session)
        await _ensure_edge_type(db_session, "supports")

        repo = EdgeRepository(db_session)
        edge = Edge(
            **make_edge(
                source_id=claim_a.id,
                target_id=claim_b.id,
                created_by=agent.id,
                edge_type="supports",
            )
        )
        created = await repo.create(edge)
        assert created.id == edge.id

        fetched = await repo.get_by_id(edge.id)
        assert fetched is not None
        assert fetched.source_id == claim_a.id
        assert fetched.target_id == claim_b.id
        assert fetched.edge_type == "supports"


@needs_db
class TestGetEdgesForClaim:
    async def test_get_edges_for_claim_both(self, db_session: AsyncSession) -> None:
        agent, _ns, claim_a, claim_b = await _setup_claims(db_session)
        await _ensure_edge_type(db_session, "supports")

        repo = EdgeRepository(db_session)
        edge = Edge(
            **make_edge(
                source_id=claim_a.id,
                target_id=claim_b.id,
                created_by=agent.id,
                edge_type="supports",
            )
        )
        await repo.create(edge)

        # Both directions
        edges_a = await repo.get_edges_for_claim(claim_a.id, direction="both")
        assert len(edges_a) >= 1

        edges_b = await repo.get_edges_for_claim(claim_b.id, direction="both")
        assert len(edges_b) >= 1

    async def test_get_edges_outgoing(self, db_session: AsyncSession) -> None:
        agent, _ns, claim_a, claim_b = await _setup_claims(db_session)
        await _ensure_edge_type(db_session, "supports")

        repo = EdgeRepository(db_session)
        edge = Edge(
            **make_edge(
                source_id=claim_a.id,
                target_id=claim_b.id,
                created_by=agent.id,
                edge_type="supports",
            )
        )
        await repo.create(edge)

        outgoing = await repo.get_edges_for_claim(claim_a.id, direction="outgoing")
        assert len(outgoing) >= 1
        assert all(e.source_id == claim_a.id for e in outgoing)

        # claim_b should have no outgoing edges
        outgoing_b = await repo.get_edges_for_claim(claim_b.id, direction="outgoing")
        assert len(outgoing_b) == 0

    async def test_get_edges_incoming(self, db_session: AsyncSession) -> None:
        agent, _ns, claim_a, claim_b = await _setup_claims(db_session)
        await _ensure_edge_type(db_session, "supports")

        repo = EdgeRepository(db_session)
        edge = Edge(
            **make_edge(
                source_id=claim_a.id,
                target_id=claim_b.id,
                created_by=agent.id,
                edge_type="supports",
            )
        )
        await repo.create(edge)

        incoming = await repo.get_edges_for_claim(claim_b.id, direction="incoming")
        assert len(incoming) >= 1
        assert all(e.target_id == claim_b.id for e in incoming)

    async def test_get_edges_by_type(self, db_session: AsyncSession) -> None:
        agent, _ns, claim_a, claim_b = await _setup_claims(db_session)
        await _ensure_edge_type(db_session, "supports")
        await _ensure_edge_type(db_session, "contradicts")

        repo = EdgeRepository(db_session)
        edge1 = Edge(
            **make_edge(
                source_id=claim_a.id,
                target_id=claim_b.id,
                created_by=agent.id,
                edge_type="supports",
            )
        )
        edge2 = Edge(
            **make_edge(
                source_id=claim_b.id,
                target_id=claim_a.id,
                created_by=agent.id,
                edge_type="contradicts",
            )
        )
        await repo.create(edge1)
        await repo.create(edge2)

        supports = await repo.get_edges_by_type("supports")
        assert len(supports) >= 1
        assert all(e.edge_type == "supports" for e in supports)

        contradicts = await repo.get_edges_by_type("contradicts")
        assert len(contradicts) >= 1
        assert all(e.edge_type == "contradicts" for e in contradicts)
