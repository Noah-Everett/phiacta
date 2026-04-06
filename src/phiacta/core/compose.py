# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Auto-compose framework for entity responses.

Provides the EntryDataProvider base class and compose helpers that
replace hardcoded extension imports in core entry endpoints.  Each
extension optionally registers a provider; the compose functions call
all registered providers and merge results into a flat response dict.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.entry import Entry

logger = logging.getLogger(__name__)


class EntryDataProvider(ABC):
    """Base class for extensions that contribute data to entry responses.

    Subclasses declare the field names they contribute, whether to include
    by default in list/detail responses, and which fields are writable
    via the unified PATCH endpoint.
    """

    #: Provider name — must match the extension plugin name.
    name: str

    #: Field names this provider contributes to responses.
    fields: frozenset[str]

    #: Whether to include in list responses by default.
    include_in_list: bool = True

    #: Whether to include in detail responses by default.
    include_in_detail: bool = True

    #: Fields writable via PATCH /entries/{id} or POST /entries.
    #: Empty if not writable.
    writable_fields: frozenset[str] = frozenset()

    #: Fields that MUST be present in the request body when creating an
    #: entry.  Validated before any DB work so failures produce clean 422s.
    required_on_create: frozenset[str] = frozenset()

    @abstractmethod
    async def get_one(self, entity_id: UUID, db: AsyncSession) -> dict | None:
        """Fetch data for a single entity.  Return None if not found."""
        ...

    @abstractmethod
    async def get_many(
        self, entity_ids: list[UUID], db: AsyncSession,
    ) -> dict[UUID, dict]:
        """Bulk-fetch data for multiple entities.

        Returns a mapping from entity_id to data dict.  Entities with no
        data are omitted from the result (not mapped to None).
        """
        ...

    #: Fields that can be used as search/list filters.
    #: Each field name can be passed as a query param to the search endpoint.
    filterable_fields: frozenset[str] = frozenset()

    def apply_search_filter(
        self,
        stmt: Any,
        entry_id_col: Any,
        field: str,
        value: str,
    ) -> Any:
        """Apply a filter to a SQLAlchemy search query statement.

        *stmt*: the current SELECT statement.
        *entry_id_col*: the Entry.id column expression for joining.
        *field*: the filter field name (must be in ``filterable_fields``).
        *value*: the raw query param value (comma-separated for multi-value).

        Returns the modified statement with any necessary joins and WHERE
        clauses added.  Raises ``NotImplementedError`` if the field is
        declared filterable but not implemented.
        """
        raise NotImplementedError(
            f"Provider {self.name!r} declares {field!r} as filterable "
            f"but does not implement apply_search_filter"
        )

    async def write(
        self,
        entity_id: UUID,
        data: dict,
        user_id: UUID,
        db: AsyncSession,
    ) -> None:
        """Write data for a single entity.

        Called for fields in ``writable_fields`` during both POST (create)
        and PATCH (update).  Implementations must handle the case where
        no row exists yet (create path).

        Subclasses that support writes must override this method.
        """
        raise NotImplementedError(
            f"Provider {self.name!r} does not support writes"
        )


def _core_fields(entry: Entry) -> dict:
    """Extract core (entries-table) fields as a dict."""
    return {
        "id": entry.id,
        "repo_name": entry.repo_name,
        "forgejo_repo_id": entry.forgejo_repo_id,
        "current_head_sha": entry.current_head_sha,
        "repo_status": entry.repo_status,
        "visibility": entry.visibility,
        "created_by": entry.created_by,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
    }


def _should_call_provider(
    provider: EntryDataProvider,
    *,
    is_list: bool,
    include: set[str] | None,
) -> bool:
    """Decide whether a provider should be called for this request.

    ``include`` is a **whitelist** — when present, only providers whose
    fields overlap with the include set are called.  When absent, the
    provider's default for the endpoint type is used.
    """
    if include is not None:
        return bool(provider.fields & include)
    return provider.include_in_list if is_list else provider.include_in_detail


def _filter_fields(
    data: dict,
    include: set[str] | None,
) -> dict:
    """Keep only the fields the caller asked for."""
    if include is not None:
        return {k: v for k, v in data.items() if k in include}
    return data


async def compose_entry_response(
    entry: Entry,
    providers: list[EntryDataProvider],
    db: AsyncSession,
    *,
    include: set[str] | None = None,
) -> dict:
    """Compose a single entry response from core fields + providers."""
    result = _core_fields(entry)

    for provider in providers:
        if not _should_call_provider(
            provider, is_list=False, include=include,
        ):
            continue
        try:
            data = await provider.get_one(entry.id, db)
        except Exception:
            logger.warning(
                "Provider %s failed for entry %s",
                provider.name, entry.id, exc_info=True,
            )
            continue
        if data is not None:
            result.update(_filter_fields(data, include))

    return result


async def compose_entry_list_responses(
    entries: list[Entry],
    providers: list[EntryDataProvider],
    db: AsyncSession,
    *,
    include: set[str] | None = None,
) -> list[dict]:
    """Compose list responses using bulk provider queries (no N+1)."""
    if not entries:
        return []

    entry_ids = [e.id for e in entries]

    # Bulk-fetch from each active provider.
    provider_maps: list[dict[UUID, dict]] = []
    active_providers: list[EntryDataProvider] = []
    for provider in providers:
        if not _should_call_provider(
            provider, is_list=True, include=include,
        ):
            continue
        try:
            pmap = await provider.get_many(entry_ids, db)
        except Exception:
            logger.warning(
                "Provider %s failed for bulk query",
                provider.name, exc_info=True,
            )
            pmap = {}
        provider_maps.append(pmap)
        active_providers.append(provider)

    # Assemble per-entry dicts.
    results: list[dict] = []
    for entry in entries:
        row = _core_fields(entry)
        for provider, pmap in zip(active_providers, provider_maps):
            data = pmap.get(entry.id)
            if data is not None:
                row.update(_filter_fields(data, include))
        results.append(row)

    return results


def parse_field_filter(raw: str | None) -> set[str] | None:
    """Parse a comma-separated field filter query param.

    Returns None if the param is absent or empty.
    """
    if not raw:
        return None
    return {f.strip() for f in raw.split(",") if f.strip()}
