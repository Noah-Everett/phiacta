# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.db.session import get_db


def create_confidence_router() -> APIRouter:
    """Create the confidence layer's API router."""
    router = APIRouter()

    @router.get("/claims/{claim_id}/status")
    async def get_epistemic_status(
        claim_id: UUID,
        db: AsyncSession = Depends(get_db),
    ) -> dict[str, Any]:
        """Get the epistemic status and confidence scores for a claim."""
        result = await db.execute(
            text(
                "SELECT id, lineage_id, content, claim_type, status, version, "
                "review_count, avg_endorsement_confidence, endorsement_count, "
                "dispute_count, epistemic_status "
                "FROM claims_with_confidence WHERE id = :claim_id"
            ),
            {"claim_id": claim_id},
        )
        row = result.mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Claim not found")
        return {
            "claim_id": str(row["id"]),
            "lineage_id": str(row["lineage_id"]),
            "content": row["content"],
            "claim_type": row["claim_type"],
            "status": row["status"],
            "version": row["version"],
            "review_count": row["review_count"],
            "avg_endorsement_confidence": (
                float(row["avg_endorsement_confidence"])
                if row["avg_endorsement_confidence"] is not None
                else None
            ),
            "endorsement_count": row["endorsement_count"],
            "dispute_count": row["dispute_count"],
            "epistemic_status": row["epistemic_status"],
        }

    @router.get("/claims")
    async def list_claims_with_confidence(
        epistemic_status: str | None = Query(None),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        db: AsyncSession = Depends(get_db),
    ) -> list[dict[str, Any]]:
        """List claims with their aggregated confidence scores."""
        query = (
            "SELECT id, lineage_id, content, claim_type, status, version, "
            "review_count, avg_endorsement_confidence, endorsement_count, "
            "dispute_count, epistemic_status "
            "FROM claims_with_confidence"
        )
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        if epistemic_status is not None:
            query += " WHERE epistemic_status = :epistemic_status"
            params["epistemic_status"] = epistemic_status

        query += " LIMIT :limit OFFSET :offset"

        result = await db.execute(text(query), params)
        rows = result.mappings().all()
        return [
            {
                "claim_id": str(row["id"]),
                "lineage_id": str(row["lineage_id"]),
                "content": row["content"],
                "claim_type": row["claim_type"],
                "status": row["status"],
                "version": row["version"],
                "review_count": row["review_count"],
                "avg_endorsement_confidence": (
                    float(row["avg_endorsement_confidence"])
                    if row["avg_endorsement_confidence"] is not None
                    else None
                ),
                "endorsement_count": row["endorsement_count"],
                "dispute_count": row["dispute_count"],
                "epistemic_status": row["epistemic_status"],
            }
            for row in rows
        ]

    return router
