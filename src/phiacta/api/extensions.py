# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.auth.dependencies import get_current_agent
from phiacta.config import get_settings
from phiacta.db.session import get_db
from phiacta.models.agent import Agent
from phiacta.models.extension import Extension
from phiacta.repositories.extension_repository import ExtensionRepository
from phiacta.schemas.common import PaginatedResponse
from phiacta.schemas.extension import (
    ExtensionHeartbeat,
    ExtensionRegister,
    ExtensionResponse,
    check_base_url_ssrf,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/extensions", tags=["extensions"])
limiter = Limiter(key_func=get_remote_address)

# Maximum number of extensions a single agent can register.
_MAX_EXTENSIONS_PER_AGENT = 50


@router.post("/register", response_model=ExtensionResponse, status_code=201)
@limiter.limit("10/minute")
async def register_extension(
    request: Request,
    body: ExtensionRegister,
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> ExtensionResponse:
    settings = get_settings()
    repo = ExtensionRepository(db)

    # Environment-aware SSRF check -- must run before health check HTTP request
    try:
        check_base_url_ssrf(
            body.base_url,
            environment=settings.environment,
            allowed_hosts=settings.extension_allowed_hosts,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Upsert: name is globally unique -- only the original registrant may update
    existing = await repo.get_by_name(body.name)
    if existing is not None:
        if existing.registered_by != agent.id:
            raise HTTPException(
                status_code=409,
                detail=f"Extension name '{body.name}' is already registered by another agent",
            )
        existing.version = body.version
        existing.base_url = body.base_url
        existing.extension_type = body.extension_type
        existing.description = body.description
        existing.manifest = body.manifest
        existing.subscribed_events = body.subscribed_events
        existing.health_status = "healthy"
        existing.last_heartbeat = datetime.now(timezone.utc)
        await db.flush()
        await db.commit()
        return ExtensionResponse.model_validate(existing)

    # Enforce global extension cap
    total = await repo.count_all()
    if total >= settings.max_extensions:
        raise HTTPException(
            status_code=409,
            detail=f"Maximum number of extensions ({settings.max_extensions}) reached",
        )

    # Enforce per-agent extension limit to prevent mass registration DoS
    agent_extension_count = await repo.count_by_agent(agent.id)
    if agent_extension_count >= _MAX_EXTENSIONS_PER_AGENT:
        raise HTTPException(
            status_code=429,
            detail=f"Maximum of {_MAX_EXTENSIONS_PER_AGENT} extensions per agent",
        )

    # Verify the extension is reachable (health check uses validated URL)
    health_status = "unknown"
    try:
        async with httpx.AsyncClient(
            timeout=settings.extension_health_check_timeout,
            follow_redirects=False,
            max_redirects=0,
        ) as client:
            resp = await client.get(f"{body.base_url}/health")
            if resp.status_code == 200:
                health_status = "healthy"
            else:
                health_status = "unhealthy"
    except httpx.HTTPError:
        logger.warning("Health check failed for %s at %s", body.name, body.base_url)

    ext = Extension(
        name=body.name,
        version=body.version,
        extension_type=body.extension_type,
        base_url=body.base_url,
        description=body.description,
        health_status=health_status,
        last_heartbeat=datetime.now(timezone.utc) if health_status == "healthy" else None,
        manifest=body.manifest,
        subscribed_events=body.subscribed_events,
        registered_by=agent.id,
    )
    ext = await repo.create(ext)
    await db.commit()
    return ExtensionResponse.model_validate(ext)


@router.get("", response_model=PaginatedResponse[ExtensionResponse])
async def list_extensions(
    extension_type: str | None = Query(None),
    healthy_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[ExtensionResponse]:
    repo = ExtensionRepository(db)
    total = await repo.count_all()
    if healthy_only:
        extensions = await repo.list_healthy(limit=limit, offset=offset)
    elif extension_type is not None:
        extensions = await repo.list_by_type(extension_type, limit=limit, offset=offset)
    else:
        extensions = await repo.list_all(limit=limit, offset=offset)
    items = [ExtensionResponse.model_validate(e) for e in extensions]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{extension_id}", response_model=ExtensionResponse)
async def get_extension(
    extension_id: UUID,
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> ExtensionResponse:
    repo = ExtensionRepository(db)
    ext = await repo.get_by_id(extension_id)
    if ext is None:
        raise HTTPException(status_code=404, detail="Extension not found")
    return ExtensionResponse.model_validate(ext)


@router.delete("/{extension_id}", status_code=204)
async def deregister_extension(
    extension_id: UUID,
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> None:
    repo = ExtensionRepository(db)
    ext = await repo.get_by_id(extension_id)
    if ext is None:
        raise HTTPException(status_code=404, detail="Extension not found")
    if ext.registered_by != agent.id:
        raise HTTPException(
            status_code=403,
            detail="Only the original registrant may deregister this extension",
        )
    await repo.delete(ext)
    await db.commit()


@router.post("/{extension_id}/heartbeat", response_model=ExtensionResponse)
@limiter.limit("60/minute")
async def heartbeat(
    request: Request,
    extension_id: UUID,
    body: ExtensionHeartbeat,
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> ExtensionResponse:
    repo = ExtensionRepository(db)
    ext = await repo.get_by_id(extension_id)
    if ext is None:
        raise HTTPException(status_code=404, detail="Extension not found")
    if ext.registered_by != agent.id:
        raise HTTPException(
            status_code=403,
            detail="Only the original registrant may send heartbeats",
        )
    ext.health_status = body.status
    ext.last_heartbeat = datetime.now(timezone.utc)
    await db.flush()
    await db.commit()
    return ExtensionResponse.model_validate(ext)
