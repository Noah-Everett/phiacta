# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.auth.dependencies import get_current_agent
from phiacta.db.session import get_db
from phiacta.extensions.dispatcher import dispatch_event
from phiacta.models.agent import Agent
from phiacta.models.bundle import Bundle
from phiacta.models.claim import Claim
from phiacta.models.relation import Relation
from phiacta.models.source import Source
from phiacta.repositories.bundle_repository import BundleRepository
from phiacta.schemas.bundle import BundleDetailResponse, BundleResponse, BundleSubmit
from phiacta.schemas.claim import ClaimResponse
from phiacta.schemas.relation import RelationResponse
from phiacta.schemas.source import SourceResponse

router = APIRouter(prefix="/bundles", tags=["bundles"])


@router.post("", response_model=BundleDetailResponse, status_code=201)
async def submit_bundle(
    body: BundleSubmit,
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> BundleDetailResponse:
    repo = BundleRepository(db)

    # Check idempotency
    existing = await repo.get_by_idempotency_key(body.idempotency_key)
    if existing is not None:
        return BundleDetailResponse.model_validate(existing)

    # Create sources
    created_sources: list[Source] = []
    for src_data in body.sources:
        source = Source(
            source_type=src_data.source_type,
            submitted_by=agent.id,
            title=src_data.title,
            external_ref=src_data.external_ref,
            content_hash=src_data.content_hash,
            attrs=src_data.attrs,
        )
        db.add(source)
        created_sources.append(source)

    # Create claims
    created_claims: list[Claim] = []
    for claim_data in body.claims:
        claim = Claim(
            lineage_id=uuid4(),
            version=1,
            content=claim_data.content,
            claim_type=claim_data.claim_type,
            namespace_id=claim_data.namespace_id,
            created_by=agent.id,
            formal_content=claim_data.formal_content,
            supersedes=claim_data.supersedes,
            status=claim_data.status,
            attrs=claim_data.attrs,
        )
        db.add(claim)
        created_claims.append(claim)

    await db.flush()

    # Create relations
    created_relations: list[Relation] = []
    for rel_data in body.relations:
        relation = Relation(
            source_id=rel_data.source_id,
            target_id=rel_data.target_id,
            relation_type=rel_data.relation_type,
            created_by=agent.id,
            strength=rel_data.strength,
            source_provenance=rel_data.source_provenance,
            attrs=rel_data.attrs,
        )
        db.add(relation)
        created_relations.append(relation)

    # Create the bundle record
    bundle = Bundle(
        idempotency_key=body.idempotency_key,
        submitted_by=agent.id,
        extension_id=body.extension_id,
        status="accepted",
        claim_count=len(created_claims),
        relation_count=len(created_relations),
        artifact_count=0,
        attrs=body.attrs,
    )
    db.add(bundle)
    await db.flush()

    await db.commit()

    claim_ids = [str(c.id) for c in created_claims]
    if claim_ids:
        await dispatch_event(
            db,
            "claim.created",
            {"claim_ids": claim_ids},
            source_extension_id=body.extension_id,
        )
    await dispatch_event(
        db,
        "bundle.submitted",
        {"bundle_id": str(bundle.id), "claim_ids": claim_ids},
        source_extension_id=body.extension_id,
    )

    return BundleDetailResponse(
        id=bundle.id,
        idempotency_key=bundle.idempotency_key,
        submitted_by=bundle.submitted_by,
        extension_id=bundle.extension_id,
        status=bundle.status,
        claim_count=bundle.claim_count,
        relation_count=bundle.relation_count,
        artifact_count=bundle.artifact_count,
        submitted_at=bundle.submitted_at,
        attrs=bundle.attrs,
        claims=[ClaimResponse.model_validate(c) for c in created_claims],
        relations=[RelationResponse.model_validate(r) for r in created_relations],
        sources=[SourceResponse.model_validate(s) for s in created_sources],
    )


@router.get("/{bundle_id}", response_model=BundleResponse)
async def get_bundle(
    bundle_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> BundleResponse:
    repo = BundleRepository(db)
    bundle = await repo.get_by_id(bundle_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Bundle not found")
    return BundleResponse.model_validate(bundle)
