# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.db.session import get_db
from phiacta.models.claim import Claim
from phiacta.schemas.claim import ClaimResponse
from phiacta.schemas.search import SearchRequest, SearchResponse, SearchResult

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search_claims(
    body: SearchRequest,
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    ts_query = func.plainto_tsquery("english", body.query)
    rank = func.ts_rank(Claim.search_tsv, ts_query)

    stmt = select(Claim, rank.label("rank")).where(Claim.search_tsv.op("@@")(ts_query))

    if body.namespace_id is not None:
        stmt = stmt.where(Claim.namespace_id == body.namespace_id)
    if body.claim_type is not None:
        stmt = stmt.where(Claim.claim_type == body.claim_type)

    stmt = stmt.order_by(rank.desc()).limit(body.limit).offset(body.offset)

    result = await db.execute(stmt)
    rows = result.all()

    results = [
        SearchResult(
            claim=ClaimResponse.model_validate(row[0]),
            rank=float(row[1]),
        )
        for row in rows
    ]

    return SearchResponse(results=results, total=len(results), query=body.query)
