# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.db.session import get_db
from phiacta.models.namespace import Namespace
from phiacta.schemas.common import PaginatedResponse
from phiacta.schemas.namespace import NamespaceCreate, NamespaceResponse

router = APIRouter(prefix="/namespaces", tags=["namespaces"])


@router.get("", response_model=PaginatedResponse[NamespaceResponse])
async def list_namespaces(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[NamespaceResponse]:
    count_result = await db.execute(select(func.count()).select_from(Namespace))
    total = count_result.scalar_one()
    result = await db.execute(select(Namespace).limit(limit).offset(offset))
    namespaces = list(result.scalars().all())
    items = [NamespaceResponse.model_validate(ns) for ns in namespaces]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=NamespaceResponse, status_code=201)
async def create_namespace(
    body: NamespaceCreate,
    db: AsyncSession = Depends(get_db),
) -> NamespaceResponse:
    namespace = Namespace(
        name=body.name,
        parent_id=body.parent_id,
        description=body.description,
        attrs=body.attrs,
    )
    db.add(namespace)
    await db.flush()
    await db.commit()
    return NamespaceResponse.model_validate(namespace)
