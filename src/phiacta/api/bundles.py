# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.auth.dependencies import get_current_agent
from phiacta.db.session import get_db
from phiacta.extensions.dispatcher import dispatch_event
from phiacta.models.agent import Agent
from phiacta.models.bundle import Bundle
from phiacta.models.claim import Claim
from phiacta.models.outbox import Outbox
from phiacta.models.reference import Reference
from phiacta.models.source import Source
from phiacta.repositories.bundle_repository import BundleRepository
from phiacta.schemas.bundle import BundleDetailResponse, BundleResponse, BundleSubmit
from phiacta.schemas.claim import ClaimResponse
from phiacta.schemas.reference import ReferenceResponse
from phiacta.schemas.source import SourceResponse
from phiacta.schemas.uri import PhiactaURI

limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/bundles", tags=["bundles"])


@router.post("", response_model=BundleDetailResponse, status_code=201)
@limiter.limit("10/minute")
async def submit_bundle(
    request: Request,
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
            title=claim_data.title,
            claim_type=claim_data.claim_type,
            format=claim_data.format,
            content_cache=claim_data.content,
            namespace_id=claim_data.namespace_id,
            created_by=agent.id,
            status=claim_data.status,
            attrs=claim_data.attrs,
            search_tsv=func.to_tsvector("english", claim_data.content),
        )
        db.add(claim)
        created_claims.append(claim)

    await db.flush()

    # Enqueue Forgejo repo creation for each claim
    for claim in created_claims:
        outbox_entry = Outbox(
            operation="create_repo",
            payload={
                "claim_id": str(claim.id),
                "title": claim.title,
                "content": claim.content_cache or "",
                "format": claim.format,
                "author_id": str(agent.id),
                "author_name": agent.name,
            },
        )
        db.add(outbox_entry)

    # Create references
    created_references: list[Reference] = []
    for ref_data in body.references:
        source_uri = PhiactaURI(str(ref_data.source_uri))
        target_uri = PhiactaURI(str(ref_data.target_uri))
        reference = Reference(
            source_uri=str(source_uri),
            target_uri=str(target_uri),
            role=ref_data.role,
            created_by=agent.id,
            source_type=source_uri.resource_type,
            target_type=target_uri.resource_type,
            source_claim_id=source_uri.claim_id,
            target_claim_id=target_uri.claim_id,
        )
        db.add(reference)
        created_references.append(reference)

    # Create the bundle record
    bundle = Bundle(
        idempotency_key=body.idempotency_key,
        submitted_by=agent.id,
        extension_id=body.extension_id,
        status="accepted",
        claim_count=len(created_claims),
        reference_count=len(created_references),
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
        reference_count=bundle.reference_count,
        artifact_count=bundle.artifact_count,
        submitted_at=bundle.submitted_at,
        attrs=bundle.attrs,
        claims=[ClaimResponse.model_validate(c) for c in created_claims],
        references=[ReferenceResponse.model_validate(r) for r in created_references],
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
