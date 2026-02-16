# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.models.agent import Agent
from phiacta.models.claim import Claim
from phiacta.models.namespace import Namespace
from phiacta.models.relation import Relation
from phiacta.repositories.relation_repository import RelationRepository
from tests.conftest import make_agent, make_claim, make_namespace, make_relation

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


@needs_db
class TestCreateAndGetRelation:
    async def test_create_and_get_relation(self, db_session: AsyncSession) -> None:
        agent, _ns, claim_a, claim_b = await _setup_claims(db_session)

        repo = RelationRepository(db_session)
        rel = Relation(
            **make_relation(
                source_id=claim_a.id,
                target_id=claim_b.id,
                created_by=agent.id,
                relation_type="supports",
            )
        )
        created = await repo.create(rel)
        assert created.id == rel.id

        fetched = await repo.get_by_id(rel.id)
        assert fetched is not None
        assert fetched.source_id == claim_a.id
        assert fetched.target_id == claim_b.id
        assert fetched.relation_type == "supports"


@needs_db
class TestGetRelationsForClaim:
    async def test_get_relations_for_claim_both(self, db_session: AsyncSession) -> None:
        agent, _ns, claim_a, claim_b = await _setup_claims(db_session)

        repo = RelationRepository(db_session)
        rel = Relation(
            **make_relation(
                source_id=claim_a.id,
                target_id=claim_b.id,
                created_by=agent.id,
                relation_type="supports",
            )
        )
        await repo.create(rel)

        # Both directions
        rels_a = await repo.get_relations_for_claim(claim_a.id, direction="both")
        assert len(rels_a) >= 1

        rels_b = await repo.get_relations_for_claim(claim_b.id, direction="both")
        assert len(rels_b) >= 1

    async def test_get_relations_outgoing(self, db_session: AsyncSession) -> None:
        agent, _ns, claim_a, claim_b = await _setup_claims(db_session)

        repo = RelationRepository(db_session)
        rel = Relation(
            **make_relation(
                source_id=claim_a.id,
                target_id=claim_b.id,
                created_by=agent.id,
                relation_type="supports",
            )
        )
        await repo.create(rel)

        outgoing = await repo.get_relations_for_claim(claim_a.id, direction="outgoing")
        assert len(outgoing) >= 1
        assert all(r.source_id == claim_a.id for r in outgoing)

        # claim_b should have no outgoing relations
        outgoing_b = await repo.get_relations_for_claim(claim_b.id, direction="outgoing")
        assert len(outgoing_b) == 0

    async def test_get_relations_incoming(self, db_session: AsyncSession) -> None:
        agent, _ns, claim_a, claim_b = await _setup_claims(db_session)

        repo = RelationRepository(db_session)
        rel = Relation(
            **make_relation(
                source_id=claim_a.id,
                target_id=claim_b.id,
                created_by=agent.id,
                relation_type="supports",
            )
        )
        await repo.create(rel)

        incoming = await repo.get_relations_for_claim(claim_b.id, direction="incoming")
        assert len(incoming) >= 1
        assert all(r.target_id == claim_b.id for r in incoming)

    async def test_get_relations_by_type(self, db_session: AsyncSession) -> None:
        agent, _ns, claim_a, claim_b = await _setup_claims(db_session)

        repo = RelationRepository(db_session)
        rel1 = Relation(
            **make_relation(
                source_id=claim_a.id,
                target_id=claim_b.id,
                created_by=agent.id,
                relation_type="supports",
            )
        )
        rel2 = Relation(
            **make_relation(
                source_id=claim_b.id,
                target_id=claim_a.id,
                created_by=agent.id,
                relation_type="contradicts",
            )
        )
        await repo.create(rel1)
        await repo.create(rel2)

        supports = await repo.get_relations_by_type("supports")
        assert len(supports) >= 1
        assert all(r.relation_type == "supports" for r in supports)

        contradicts = await repo.get_relations_by_type("contradicts")
        assert len(contradicts) >= 1
        assert all(r.relation_type == "contradicts" for r in contradicts)
