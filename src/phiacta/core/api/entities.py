# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Entity resolve endpoint — given any UUID, resolve to type + data."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.api.entry_guards import check_archive_visibility
from phiacta.core.auth.dependencies import get_optional_user
from phiacta.core.compose import compose_entry_response
from phiacta.core.db.session import get_db
from phiacta.core.models.user import User
from phiacta.core.repositories.entity_repository import EntityRepository
from phiacta.core.repositories.entry_repository import EntryRepository
from phiacta.core.repositories.user_repository import UserRepository
from phiacta.core.schemas.auth import UserResponse

router = APIRouter(prefix="/entities", tags=["entities"])


def _get_providers(request: Request):  # noqa: ANN202
    """Reuse the same provider lookup as the entries router."""
    registry = getattr(request.app.state, "plugin_registry", None)
    if registry is not None:
        return registry.get_entry_data_providers()
    return getattr(request.app.state, "entry_data_providers", [])


@router.get("/{entity_id}")
async def resolve_entity(
    request: Request,
    entity_id: UUID,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    entity = await EntityRepository(db).get_by_id(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    base = {
        "id": entity.id,
        "entity_type": entity.entity_type,
        "parent_id": entity.parent_id,
        "created_by": entity.created_by,
        "created_at": entity.created_at,
    }

    if entity.entity_type == "entry":
        entry = await EntryRepository(db).get_by_id(entity_id)
        if entry is None:
            return base
        check_archive_visibility(entry, user)
        providers = _get_providers(request)
        composed = await compose_entry_response(entry, providers, db)
        base.update(composed)

    elif entity.entity_type == "user":
        user = await UserRepository(db).get_by_id(entity_id)
        if user is not None:
            base.update(UserResponse.model_validate(user).model_dump(mode="json"))

    return base
