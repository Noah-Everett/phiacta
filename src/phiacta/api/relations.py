# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.db.session import get_db
from phiacta.models.relation import Relation
from phiacta.repositories.relation_repository import RelationRepository
from phiacta.schemas.common import PaginatedResponse
from phiacta.schemas.relation import RelationCreate, RelationResponse

router = APIRouter(prefix="/relations", tags=["relations"])


@router.get("", response_model=PaginatedResponse[RelationResponse])
async def list_relations(
    relation_type: str | None = Query(None),
    source_id: UUID | None = Query(None),
    target_id: UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[RelationResponse]:
    repo = RelationRepository(db)
    if relation_type is not None:
        relations = await repo.get_relations_by_type(relation_type)
    elif source_id is not None:
        relations = await repo.get_relations_for_claim(source_id, direction="outgoing")
    elif target_id is not None:
        relations = await repo.get_relations_for_claim(target_id, direction="incoming")
    else:
        relations = await repo.list_all(limit=limit, offset=offset)
    items = [RelationResponse.model_validate(r) for r in relations]
    return PaginatedResponse(items=items, total=len(items), limit=limit, offset=offset)


@router.post("", response_model=RelationResponse, status_code=201)
async def create_relation(
    body: RelationCreate,
    db: AsyncSession = Depends(get_db),
) -> RelationResponse:
    repo = RelationRepository(db)
    relation = Relation(
        source_id=body.source_id,
        target_id=body.target_id,
        relation_type=body.relation_type,
        created_by=body.created_by,
        strength=body.strength,
        source_provenance=body.source_provenance,
        attrs=body.attrs,
    )
    relation = await repo.create(relation)
    await db.commit()
    return RelationResponse.model_validate(relation)
