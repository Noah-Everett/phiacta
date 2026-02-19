# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.db.session import get_db

_VIEW_COLUMNS = (
    "id, title, claim_type, status, "
    "signal_count, interaction_count, weighted_agree_confidence, "
    "agree_count, disagree_count, neutral_count, epistemic_status"
)

# Prebuilt SQL strings — no user input touches column names
_SQL_SINGLE = text(
    f"SELECT {_VIEW_COLUMNS} FROM claims_with_confidence WHERE id = :claim_id"
)
_SQL_LIST = text(
    f"SELECT {_VIEW_COLUMNS} FROM claims_with_confidence"
    " LIMIT :limit OFFSET :offset"
)
_SQL_LIST_FILTERED = text(
    f"SELECT {_VIEW_COLUMNS} FROM claims_with_confidence"
    " WHERE epistemic_status = :epistemic_status"
    " LIMIT :limit OFFSET :offset"
)


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a claims_with_confidence row mapping to a response dict."""
    return {
        "claim_id": str(row["id"]),
        "title": row["title"],
        "claim_type": row["claim_type"],
        "status": row["status"],
        "signal_count": row["signal_count"],
        "interaction_count": row["interaction_count"],
        "weighted_agree_confidence": (
            float(row["weighted_agree_confidence"])
            if row["weighted_agree_confidence"] is not None
            else None
        ),
        "agree_count": row["agree_count"],
        "disagree_count": row["disagree_count"],
        "neutral_count": row["neutral_count"],
        "epistemic_status": row["epistemic_status"],
    }


def create_confidence_router() -> APIRouter:
    """Create the confidence layer's API router."""
    router = APIRouter()

    @router.get("/claims/{claim_id}/status")
    async def get_epistemic_status(
        claim_id: UUID,
        db: AsyncSession = Depends(get_db),
    ) -> dict[str, Any]:
        """Get the epistemic status and confidence scores for a claim."""
        result = await db.execute(_SQL_SINGLE, {"claim_id": claim_id})
        row = result.mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Claim not found")
        return _row_to_dict(row)

    @router.get("/claims")
    async def list_claims_with_confidence(
        epistemic_status: str | None = Query(None),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        db: AsyncSession = Depends(get_db),
    ) -> list[dict[str, Any]]:
        """List claims with their aggregated confidence scores."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        if epistemic_status is not None:
            params["epistemic_status"] = epistemic_status
            result = await db.execute(_SQL_LIST_FILTERED, params)
        else:
            result = await db.execute(_SQL_LIST, params)

        rows = result.mappings().all()
        return [_row_to_dict(row) for row in rows]

    return router
