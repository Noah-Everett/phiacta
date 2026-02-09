# API Design Specification

*Complete REST API design for the NewPublishing knowledge backend. Read `docs/design/synthesis.md` for schema design and `docs/implementation/architecture.md` for the technical foundation this document builds on.*

---

## 1. API Versioning Strategy

### Version Prefix

All API endpoints are prefixed with the API version: `/v1/`. This is a URL path segment, not a header or query parameter. Path-based versioning is explicit, discoverable, and works with all HTTP clients without special configuration.

```
https://api.newpublishing.example.com/v1/claims
https://api.newpublishing.example.com/v1/bundles
https://api.newpublishing.example.com/v1/query/search
```

### Versioning Rules

**What constitutes a new major version (v1 → v2):**

- Removing or renaming an endpoint
- Removing or renaming a required field
- Changing the type or semantics of an existing field
- Changing error codes or HTTP status codes for existing error conditions
- Breaking changes to authentication mechanisms

**What does NOT require a new version:**

- Adding new endpoints
- Adding new optional fields to requests or responses
- Adding new enum values where clients handle unknown values gracefully
- Performance improvements
- Bug fixes that correct behavior to match documentation

### Deprecation Policy

When a new API version is released:

1. **Simultaneous support.** Both versions are served concurrently for a minimum of 6 months.
2. **Deprecation headers.** Deprecated endpoints return headers indicating their status:
   ```
   Deprecation: true
   Sunset: Sat, 08 Aug 2026 00:00:00 GMT
   Link: <https://api.newpublishing.example.com/v2/claims>; rel="successor-version"
   ```
3. **Documentation update.** The API reference marks deprecated endpoints with clear migration guidance.
4. **Monitoring.** Usage of deprecated endpoints is logged. High-traffic extensions receive direct outreach before sunset.
5. **Sunset.** After the sunset date, deprecated endpoints return `410 Gone` with a body explaining the migration path.

### Extension Compatibility

Extensions declare their required API version in the manifest:

```json
{
  "api_version_required": "v1"
}
```

The backend validates this during registration. Extensions targeting `/v1/` continue working after `/v2/` launches — no forced migration. Extensions can upgrade at their own pace during the overlap period.

---

## 2. Authentication and Authorization

### 2.1 Authentication Methods

The API supports three authentication methods, used for different client types:

#### API Keys (Extensions and Services)

Primary authentication for extensions and machine-to-machine integrations.

```
Authorization: Bearer ext_key_live_abc123def456...
```

**Key properties:**
- Prefixed with `ext_key_live_` (production) or `ext_key_test_` (development).
- 64 characters of random data after the prefix.
- Stored as bcrypt hashes in the database; raw key shown exactly once at creation.
- Scoped to specific capabilities declared in the extension manifest.
- Per-key rate limits configurable at registration.

**Key lifecycle:**
- Created during extension registration (`POST /v1/extensions/register`).
- Revoked via `DELETE /v1/extensions/{extension_id}` or `POST /v1/extensions/{extension_id}/rotate-key`.
- No expiration by default; optionally set `expires_at` for time-limited access.

#### JWT Tokens (Web/Mobile Applications)

For user-facing applications where individual users need authenticated access. **Deferred to v2** — v1 focuses on extension-to-backend communication. The design is documented here for future implementation.

```
Authorization: Bearer eyJhbGciOiJFUzI1NiIs...
```

**Token properties:**
- Signed with ES256 (ECDSA with P-256 curve).
- Short-lived access tokens (15 minutes).
- Long-lived refresh tokens (7 days) stored as HTTP-only cookies or secure storage.
- Claims include: `sub` (user ID), `aud` (audience), `exp` (expiration), `scopes` (permissions).

**Token endpoints (v2):**
```
POST /v2/auth/token         # Exchange credentials for tokens
POST /v2/auth/refresh       # Refresh an access token
POST /v2/auth/revoke        # Revoke a refresh token
```

#### OAuth2 (Third-Party Integrations)

For third-party applications accessing the API on behalf of users. **Deferred to v2.**

Planned flows:
- Authorization Code with PKCE (web and native apps)
- Client Credentials (service accounts)

OAuth2 endpoints would live under `/v2/oauth/`.

### 2.2 Authorization Model

Authorization is capability-based. Each API key or token has a set of scopes that determine permitted operations.

#### Scopes

| Scope | Permits |
|-------|---------|
| `bundles:write` | Submit knowledge bundles |
| `claims:read` | Read claims, edges, and provenance |
| `claims:write` | Directly create/update claims (admin, bypasses bundle validation) |
| `search:read` | Execute search and traversal queries |
| `extensions:read` | List registered extensions |
| `extensions:write` | Register and manage extensions |
| `webhooks:manage` | Create, update, and delete webhook subscriptions |
| `admin` | Full access (backend operators only) |

Extensions receive scopes based on their declared capabilities:
- `can_write: true` → `bundles:write`
- `can_read: true` → `claims:read`, `search:read`
- Webhook URL declared → `webhooks:manage` (for that extension's webhooks only)

#### Enforcement

Scope enforcement happens in the API layer via FastAPI dependencies:

```python
# api/deps.py
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

async def require_scope(
    required: str,
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: AsyncSession = Depends(get_db),
) -> Agent:
    """Verify the request has the required scope."""
    agent = await verify_api_key(credentials.credentials, db)
    if required not in agent.scopes:
        raise HTTPException(
            status_code=403,
            detail={"code": "INSUFFICIENT_SCOPE", "required": required},
        )
    return agent

# Usage in routes
@router.post("/bundles")
async def submit_bundle(
    bundle: BundleSubmit,
    agent: Agent = Depends(require_scope("bundles:write")),
):
    ...
```

### 2.3 Contributor Identity

Extensions often act on behalf of end users (e.g., a researcher using a paper ingestion tool). The API distinguishes between:

- **Agent**: The extension submitting the request (authenticated via API key).
- **Contributor**: The human who originated the knowledge (passed as metadata).

Contributors are identified by `contributor_id` in bundle submissions:

```json
{
  "idempotency_key": "paper-doi-10.1234/abc",
  "contributor_id": "orcid:0000-0002-1825-0097",
  "claims": [...]
}
```

The backend records both the agent and contributor in provenance. Contributor authentication is the extension's responsibility — the backend trusts the extension's assertion.

---

## 3. Core Endpoints

### 3.1 Claims API

Claims are the fundamental unit of knowledge. The Claims API provides CRUD operations with versioning support.

#### Create Claim (via Bundle)

Claims are not created directly via `POST /v1/claims`. They are created atomically as part of bundles to ensure relational integrity. See Section 3.2.

#### Get Claim

```
GET /v1/claims/{claim_id}
```

Retrieves a single claim by ID.

**Path Parameters:**
- `claim_id` (UUID, required): The claim's unique identifier.

**Query Parameters:**
- `include` (string[], optional): Additional data to include. Options: `provenance`, `edges`, `reviews`, `artifacts`, `lineage`.
- `version` (int, optional): Specific version number. Omit for latest.

**Response:** `200 OK`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "lineage_id": "550e8400-e29b-41d4-a716-446655440001",
  "version": 3,
  "content": "Compound X reduces inflammation by 40% in murine models",
  "claim_type": "empirical",
  "namespace": {
    "id": "ns-biology-immunology",
    "name": "biology.immunology"
  },
  "formal_content": null,
  "attrs": {
    "sample_size": 120,
    "p_value": "0.003",
    "effect_size": "0.4"
  },
  "created_at": "2026-02-08T10:30:00Z",
  "created_by": {
    "id": "agent-paper-ingestion",
    "name": "Paper Ingestion",
    "type": "extension"
  },
  "is_latest": true,
  "provenance": [...],  // if include=provenance
  "edges": [...],        // if include=edges
  "reviews": [...]       // if include=reviews
}
```

**Errors:**
- `404 NOT_FOUND`: Claim does not exist.
- `404 VERSION_NOT_FOUND`: Requested version does not exist.

#### List Claims

```
GET /v1/claims
```

Lists claims with filtering and pagination.

**Query Parameters:**
- `namespace` (string, optional): Filter by namespace (exact match or prefix with `*`).
- `claim_type` (string, optional): Filter by claim type.
- `created_by` (UUID, optional): Filter by creating agent.
- `created_after` (datetime, optional): ISO 8601 timestamp.
- `created_before` (datetime, optional): ISO 8601 timestamp.
- `lineage_id` (UUID, optional): Filter to all versions of a specific claim.
- `latest_only` (bool, default true): Return only the latest version of each claim.
- `limit` (int, default 50, max 200): Number of results per page.
- `cursor` (string, optional): Pagination cursor from previous response.
- `include` (string[], optional): Additional data to include per claim.

**Response:** `200 OK`

```json
{
  "claims": [...],
  "total_count": 1523,
  "next_cursor": "eyJpZCI6IjU1MGU4NDAw...",
  "has_more": true
}
```

#### Update Claim

```
PATCH /v1/claims/{claim_id}
```

Creates a new version of a claim. The original version is preserved; the new version is linked via `supersedes` edge and shares the same `lineage_id`.

**Request Body:**

```json
{
  "content": "Compound X reduces inflammation by 45% in murine models",
  "attrs": {
    "sample_size": 180,
    "p_value": "0.001",
    "effect_size": "0.45",
    "correction_note": "Updated with larger sample from follow-up study"
  },
  "source_id": "source-followup-paper-uuid",
  "reason": "Incorporated results from replication study"
}
```

**Required scope:** `claims:write` (admin) or `bundles:write` with ownership of the claim.

**Response:** `200 OK` with the new claim version.

**Constraints:**
- Only the latest version of a claim can be updated.
- Updates by non-admin agents require ownership (agent created the claim or its lineage).

#### Delete Claim (Soft)

```
DELETE /v1/claims/{claim_id}
```

Marks a claim as retracted. Does not delete data; creates a `retracted` edge to a retraction notice claim.

**Request Body (optional):**

```json
{
  "reason": "Computational error in original analysis",
  "retraction_source_id": "source-retraction-notice-uuid"
}
```

**Required scope:** `claims:write` (admin) or ownership.

**Response:** `200 OK`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "retracted",
  "retraction_edge_id": "edge-uuid"
}
```

Retracted claims remain queryable with a `retracted: true` flag. They are excluded from search results by default.

### 3.2 Bundles API

Bundles are the atomic write unit. A bundle contains claims, edges, and artifacts that are committed together — all succeed or all fail.

#### Submit Bundle

```
POST /v1/bundles
```

Submits a knowledge bundle for ingestion.

**Request Body:**

```json
{
  "idempotency_key": "paper-doi-10.1234/abc-v2",
  "contributor_id": "orcid:0000-0002-1825-0097",
  "source": {
    "source_type": "paper",
    "title": "Effects of Compound X on Inflammation",
    "external_ref": "doi:10.1234/abc",
    "content_hash": "sha256:a1b2c3d4...",
    "attrs": {
      "authors": ["Jane Doe", "John Smith"],
      "journal": "Journal of Immunology",
      "year": 2026
    }
  },
  "claims": [
    {
      "temp_id": "c1",
      "content": "Compound X reduces inflammation by 40%",
      "claim_type": "empirical",
      "namespace": "biology.immunology",
      "confidence": 0.95,
      "attrs": {"sample_size": 120}
    },
    {
      "temp_id": "c2",
      "content": "The effect is mediated by NF-kB pathway inhibition",
      "claim_type": "mechanistic",
      "namespace": "biology.immunology",
      "confidence": 0.85
    }
  ],
  "edges": [
    {
      "source_temp_id": "c2",
      "target_temp_id": "c1",
      "edge_type": "explains"
    },
    {
      "source_temp_id": "c1",
      "target_external_ref": "doi:10.5678/prior-study",
      "edge_type": "corroborates"
    }
  ],
  "artifacts": [
    {
      "temp_id": "a1",
      "artifact_type": "figure",
      "description": "Dose-response curve for Compound X",
      "storage_ref": "s3://newpub-artifacts/fig1-abc123.png",
      "linked_claim_temp_ids": ["c1"]
    }
  ]
}
```

**Required scope:** `bundles:write`

**Response:** `201 Created`

```json
{
  "bundle_id": "bundle-uuid",
  "status": "accepted",
  "created_claims": [
    {"temp_id": "c1", "id": "claim-uuid-1", "version": 1},
    {"temp_id": "c2", "id": "claim-uuid-2", "version": 1}
  ],
  "created_edges": [
    {"id": "edge-uuid-1", "source_id": "claim-uuid-2", "target_id": "claim-uuid-1"},
    {"id": "edge-uuid-2", "source_id": "claim-uuid-1", "target_id": null, "pending_ref": "doi:10.5678/prior-study"}
  ],
  "created_artifacts": [
    {"temp_id": "a1", "id": "artifact-uuid-1"}
  ],
  "warnings": [
    "Claim c2 has confidence < 0.9 for a mechanistic claim"
  ],
  "pending_references": [
    {"external_ref": "doi:10.5678/prior-study", "status": "pending"}
  ]
}
```

**Validation:**
- `temp_id` values must be unique within the bundle.
- All edge references must resolve (either to a `temp_id` in the bundle, an existing claim `id`, or an `external_ref`).
- `edge_type` must be a registered type in `edge_types`.
- `namespace` must exist or the bundle must declare `create_namespace: true`.
- `claim_type` must be in the extension's declared `claim_types` (if manifest restricts).

**Errors:**
- `409 IDEMPOTENCY_CONFLICT`: A bundle with this key was already submitted with different content.
- `422 VALIDATION_FAILED`: Bundle content is invalid (details in response).
- `429 RATE_LIMITED`: Too many submissions; retry after backoff.

#### Get Bundle

```
GET /v1/bundles/{bundle_id}
```

Retrieves metadata about a submitted bundle.

**Response:** `200 OK`

```json
{
  "id": "bundle-uuid",
  "idempotency_key": "paper-doi-10.1234/abc-v2",
  "status": "accepted",
  "submitted_by": "agent-paper-ingestion",
  "contributor_id": "orcid:0000-0002-1825-0097",
  "extension_id": "ext-paper-ingest-v2",
  "claim_count": 2,
  "edge_count": 2,
  "artifact_count": 1,
  "submitted_at": "2026-02-08T10:30:00Z",
  "source_id": "source-uuid"
}
```

### 3.3 Evidence API

Evidence relationships are modeled as edges with specific types. The Evidence API provides convenient access patterns for evidential reasoning.

#### Get Evidence For Claim

```
GET /v1/claims/{claim_id}/evidence
```

Retrieves claims that provide evidential support or contradiction for the target claim.

**Query Parameters:**
- `relationship` (string, optional): Filter by relationship type. Options: `supports`, `contradicts`, `corroborates`, `all`. Default: `all`.
- `min_strength` (float, optional): Minimum edge strength (0.0-1.0).
- `depth` (int, default 1, max 5): Transitive depth for evidence chains.
- `include_retracted` (bool, default false): Include retracted evidence.

**Response:** `200 OK`

```json
{
  "claim_id": "target-claim-uuid",
  "evidence": {
    "supports": [
      {
        "claim": {...},
        "edge": {
          "id": "edge-uuid",
          "edge_type": "supports",
          "strength": 0.9,
          "asserted_by": "agent-uuid",
          "attrs": {"methodology_match": true}
        },
        "chain_depth": 1
      }
    ],
    "contradicts": [...],
    "corroborates": [...]
  },
  "summary": {
    "total_supporting": 5,
    "total_contradicting": 1,
    "total_corroborating": 3,
    "net_support": 0.72
  }
}
```

#### Link Evidence

```
POST /v1/claims/{claim_id}/evidence
```

Creates an evidential edge from an existing claim to the target claim.

**Request Body:**

```json
{
  "source_claim_id": "evidence-claim-uuid",
  "relationship": "supports",
  "strength": 0.85,
  "attrs": {
    "replication_type": "direct",
    "sample_overlap": false
  }
}
```

**Required scope:** `bundles:write`

**Response:** `201 Created`

```json
{
  "edge_id": "edge-uuid",
  "source_id": "evidence-claim-uuid",
  "target_id": "target-claim-uuid",
  "edge_type": "supports",
  "strength": 0.85
}
```

### 3.4 Confidence API

Confidence scores are computed at query time, not stored. The Confidence API provides read-only views of calculated scores based on reviews and evidence.

#### Get Claim Confidence

```
GET /v1/claims/{claim_id}/confidence
```

Computes the current confidence assessment for a claim.

**Query Parameters:**
- `model` (string, optional): Confidence computation model. Options: `simple_average`, `weighted_reviewer`, `bayesian`, `evidence_chain`. Default: `weighted_reviewer`.
- `reviewer_filter` (UUID[], optional): Only consider reviews from these agents.
- `trust_profile` (string, optional): Named trust profile to apply (predefined reviewer weights).

**Response:** `200 OK`

```json
{
  "claim_id": "claim-uuid",
  "computed_at": "2026-02-08T12:00:00Z",
  "model": "weighted_reviewer",
  "confidence": {
    "score": 0.78,
    "lower_bound": 0.65,
    "upper_bound": 0.88,
    "components": {
      "review_based": 0.82,
      "evidence_based": 0.75,
      "provenance_factor": 0.95
    }
  },
  "reviews_considered": 12,
  "evidence_chains_considered": 3,
  "caveats": [
    "2 reviews from low-trust agents excluded",
    "1 contradicting claim not yet addressed"
  ]
}
```

#### Get Confidence Distribution

```
GET /v1/claims/{claim_id}/confidence/distribution
```

Returns the distribution of reviewer assessments.

**Response:** `200 OK`

```json
{
  "claim_id": "claim-uuid",
  "distribution": {
    "buckets": [
      {"range": [0.0, 0.2], "count": 0},
      {"range": [0.2, 0.4], "count": 1},
      {"range": [0.4, 0.6], "count": 2},
      {"range": [0.6, 0.8], "count": 7},
      {"range": [0.8, 1.0], "count": 2}
    ],
    "mean": 0.72,
    "median": 0.75,
    "std_dev": 0.12
  },
  "by_reviewer_type": {
    "human": {"mean": 0.75, "count": 8},
    "ai": {"mean": 0.68, "count": 4}
  }
}
```

### 3.5 Ingestion API

The Ingestion API triggers paper/source processing by input extensions.

#### Trigger Ingestion

```
POST /v1/ingest
```

Requests ingestion of a source. The backend routes to the appropriate input extension.

**Request Body:**

```json
{
  "source_type": "paper",
  "external_ref": "doi:10.1234/abc",
  "priority": "normal",
  "extension_id": "ext-paper-ingest-v2",
  "callback_url": "https://my-app.example.com/ingestion-complete",
  "attrs": {
    "force_reprocess": false,
    "extract_figures": true
  }
}
```

**Required scope:** `bundles:write`

**Response:** `202 Accepted`

```json
{
  "job_id": "job-uuid",
  "status": "queued",
  "extension_id": "ext-paper-ingest-v2",
  "estimated_completion": "2026-02-08T10:35:00Z"
}
```

#### Get Ingestion Status

```
GET /v1/ingest/{job_id}
```

**Response:** `200 OK`

```json
{
  "job_id": "job-uuid",
  "status": "completed",
  "source_id": "source-uuid",
  "bundle_id": "bundle-uuid",
  "claims_created": 15,
  "edges_created": 22,
  "completed_at": "2026-02-08T10:33:00Z"
}
```

**Status values:** `queued`, `processing`, `completed`, `failed`, `cancelled`.

### 3.6 Search API

The Search API supports semantic search (via pgvector embeddings) and structural queries (via graph traversal).

#### Semantic Search

```
POST /v1/query/search
```

Searches claims using natural language.

**Request Body:**

```json
{
  "query": "effects of compound X on inflammation pathways",
  "top_k": 20,
  "min_similarity": 0.7,
  "filters": {
    "namespace_prefix": "biology",
    "claim_types": ["empirical", "mechanistic"],
    "created_after": "2024-01-01T00:00:00Z",
    "exclude_retracted": true
  },
  "include": ["provenance", "confidence"],
  "highlight": true
}
```

**Required scope:** `search:read`

**Response:** `200 OK`

```json
{
  "results": [
    {
      "claim": {...},
      "similarity": 0.89,
      "highlight": "effects of <em>compound X</em> on <em>inflammation</em>...",
      "confidence": {"score": 0.78},
      "provenance": [...]
    }
  ],
  "total_matches": 47,
  "query_embedding_model": "text-embedding-3-small",
  "search_time_ms": 45
}
```

#### Structural Graph Traversal

```
POST /v1/query/traverse
```

Traverses the claim graph from a starting point.

**Request Body:**

```json
{
  "start": "claim-uuid",
  "direction": "both",
  "edge_types": ["supports", "contradicts", "depends_on"],
  "max_depth": 3,
  "max_nodes": 100,
  "filters": {
    "min_edge_strength": 0.5,
    "exclude_retracted": true
  },
  "include": ["edges", "confidence"]
}
```

**Response:** `200 OK`

```json
{
  "nodes": [
    {"claim": {...}, "depth": 0},
    {"claim": {...}, "depth": 1},
    ...
  ],
  "edges": [
    {
      "id": "edge-uuid",
      "source_id": "claim-uuid-1",
      "target_id": "claim-uuid-2",
      "edge_type": "supports",
      "strength": 0.9
    }
  ],
  "graph_stats": {
    "total_nodes": 23,
    "total_edges": 31,
    "max_depth_reached": 3,
    "truncated": false
  }
}
```

#### Specialized Views

```
POST /v1/query/view
```

Requests a pre-defined view optimized for specific use cases.

**Request Body:**

```json
{
  "view_type": "paper",
  "root": "source-uuid",
  "options": {
    "include_figures": true,
    "include_citations": true,
    "format": "structured"
  }
}
```

**Available view types:**
- `paper`: Reconstruct a paper's claims, evidence, and citations.
- `proof_tree`: Show the dependency tree for a theorem/derivation.
- `comparison`: Side-by-side view of claims from multiple sources on the same topic.
- `evidence_map`: Visual map of supporting and contradicting evidence.
- `lineage`: Version history of a claim across all updates.

**Response:** `200 OK` (structure varies by view type)

---

## 4. Request/Response Schemas

All request and response bodies use JSON. Schemas are defined with Pydantic v2 and exported as JSON Schema for client code generation.

### 4.1 Common Types

```python
# schemas/common.py
from datetime import datetime
from typing import Any
from uuid import UUID
from pydantic import BaseModel, Field


class PaginatedRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = None


class PaginatedResponse[T](BaseModel):
    items: list[T]
    total_count: int
    next_cursor: str | None
    has_more: bool


class ErrorDetail(BaseModel):
    field: str | None = None
    message: str
    code: str


class ErrorResponse(BaseModel):
    error: dict[str, Any] = Field(
        ...,
        examples=[{
            "code": "VALIDATION_FAILED",
            "message": "Bundle validation failed",
            "details": [{"field": "claims[0].content", "message": "Required field", "code": "REQUIRED"}],
            "request_id": "req-uuid"
        }]
    )


class AgentRef(BaseModel):
    id: UUID
    name: str
    type: str  # "human", "extension", "pipeline"


class NamespaceRef(BaseModel):
    id: str
    name: str


class Attrs(BaseModel):
    """Arbitrary key-value metadata."""
    model_config = {"extra": "allow"}
```

### 4.2 Claim Schemas

```python
# schemas/claims.py
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field
from .common import AgentRef, NamespaceRef, Attrs


class ClaimBase(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    claim_type: str = Field(..., pattern=r"^[a-z_]+$")
    namespace: str | None = None
    formal_content: str | None = None
    attrs: Attrs = Field(default_factory=Attrs)


class ClaimCreate(ClaimBase):
    """Used within bundle submissions."""
    temp_id: str = Field(..., pattern=r"^[a-zA-Z0-9_-]+$")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class ClaimRead(ClaimBase):
    id: UUID
    lineage_id: UUID
    version: int
    namespace_ref: NamespaceRef | None = None
    created_at: datetime
    created_by: AgentRef
    is_latest: bool
    is_retracted: bool = False

    # Optional includes
    provenance: list["ProvenanceRead"] | None = None
    edges: list["EdgeRead"] | None = None
    reviews: list["ReviewRead"] | None = None
    artifacts: list["ArtifactRead"] | None = None


class ClaimUpdate(BaseModel):
    content: str | None = None
    formal_content: str | None = None
    attrs: Attrs | None = None
    source_id: UUID | None = None
    reason: str | None = None


class ClaimListParams(BaseModel):
    namespace: str | None = None
    claim_type: str | None = None
    created_by: UUID | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    lineage_id: UUID | None = None
    latest_only: bool = True
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = None
    include: list[str] = Field(default_factory=list)
```

### 4.3 Bundle Schemas

```python
# schemas/bundles.py
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field
from .claims import ClaimCreate
from .common import Attrs


class SourceCreate(BaseModel):
    source_type: str
    title: str | None = None
    external_ref: str | None = None
    content_hash: str | None = None
    attrs: Attrs = Field(default_factory=Attrs)


class EdgeCreate(BaseModel):
    source_temp_id: str
    target_temp_id: str | None = None
    target_id: UUID | None = None
    target_external_ref: str | None = None
    edge_type: str
    strength: float | None = Field(default=None, ge=0.0, le=1.0)
    attrs: Attrs = Field(default_factory=Attrs)


class ArtifactCreate(BaseModel):
    temp_id: str
    artifact_type: str
    description: str | None = None
    storage_ref: str | None = None
    content_inline: str | None = None
    structured_data: dict | None = None
    linked_claim_temp_ids: list[str] = Field(default_factory=list)


class BundleSubmit(BaseModel):
    idempotency_key: str = Field(..., min_length=1, max_length=256)
    contributor_id: str | None = None
    source: SourceCreate
    claims: list[ClaimCreate] = Field(..., min_length=1, max_length=500)
    edges: list[EdgeCreate] = Field(default_factory=list)
    artifacts: list[ArtifactCreate] = Field(default_factory=list)
    create_namespace: bool = False


class ClaimMapping(BaseModel):
    temp_id: str
    id: UUID
    version: int


class EdgeMapping(BaseModel):
    id: UUID
    source_id: UUID
    target_id: UUID | None
    pending_ref: str | None = None


class ArtifactMapping(BaseModel):
    temp_id: str
    id: UUID


class PendingRefStatus(BaseModel):
    external_ref: str
    status: str  # "pending", "resolved"
    resolved_to: UUID | None = None


class BundleResponse(BaseModel):
    bundle_id: UUID
    status: str  # "accepted", "rejected"
    created_claims: list[ClaimMapping]
    created_edges: list[EdgeMapping]
    created_artifacts: list[ArtifactMapping]
    warnings: list[str] = Field(default_factory=list)
    pending_references: list[PendingRefStatus] = Field(default_factory=list)
```

### 4.4 Query Schemas

```python
# schemas/queries.py
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class SearchFilters(BaseModel):
    namespace_prefix: str | None = None
    claim_types: list[str] | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    exclude_retracted: bool = True
    min_confidence: float | None = None


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(default=20, ge=1, le=100)
    min_similarity: float = Field(default=0.5, ge=0.0, le=1.0)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    include: list[str] = Field(default_factory=list)
    highlight: bool = False


class SearchResult(BaseModel):
    claim: "ClaimRead"
    similarity: float
    highlight: str | None = None
    confidence: dict | None = None
    provenance: list | None = None


class SearchResponse(BaseModel):
    results: list[SearchResult]
    total_matches: int
    query_embedding_model: str
    search_time_ms: int


class TraverseFilters(BaseModel):
    min_edge_strength: float | None = None
    exclude_retracted: bool = True
    edge_types_exclude: list[str] | None = None


class TraverseRequest(BaseModel):
    start: UUID
    direction: str = Field(default="both", pattern="^(outgoing|incoming|both)$")
    edge_types: list[str] | None = None
    max_depth: int = Field(default=3, ge=1, le=10)
    max_nodes: int = Field(default=100, ge=1, le=1000)
    filters: TraverseFilters = Field(default_factory=TraverseFilters)
    include: list[str] = Field(default_factory=list)


class GraphNode(BaseModel):
    claim: "ClaimRead"
    depth: int


class GraphEdge(BaseModel):
    id: UUID
    source_id: UUID
    target_id: UUID
    edge_type: str
    strength: float | None


class GraphStats(BaseModel):
    total_nodes: int
    total_edges: int
    max_depth_reached: int
    truncated: bool


class TraverseResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    graph_stats: GraphStats


class ViewRequest(BaseModel):
    view_type: str
    root: UUID
    options: dict = Field(default_factory=dict)
```

---

## 5. Error Handling

### 5.1 Error Response Format

All error responses use a consistent JSON structure:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable summary",
    "details": [...],
    "request_id": "req-uuid-for-tracing"
  }
}
```

### 5.2 Error Codes and HTTP Status Mapping

| HTTP Status | Error Code | Description |
|-------------|------------|-------------|
| 400 | `BAD_REQUEST` | Malformed request (invalid JSON, missing required headers) |
| 400 | `INVALID_PARAMETER` | Query parameter or path parameter is invalid |
| 401 | `UNAUTHENTICATED` | Missing or invalid authentication credentials |
| 401 | `TOKEN_EXPIRED` | JWT token has expired |
| 403 | `FORBIDDEN` | Valid credentials but insufficient permissions |
| 403 | `INSUFFICIENT_SCOPE` | API key lacks required scope |
| 403 | `CAPABILITY_DENIED` | Extension attempted an undeclared capability |
| 404 | `NOT_FOUND` | Requested resource does not exist |
| 404 | `CLAIM_NOT_FOUND` | Specific claim does not exist |
| 404 | `VERSION_NOT_FOUND` | Requested claim version does not exist |
| 404 | `EXTENSION_NOT_FOUND` | Extension is not registered |
| 409 | `CONFLICT` | Request conflicts with current state |
| 409 | `IDEMPOTENCY_CONFLICT` | Bundle with this key exists with different content |
| 409 | `CONCURRENT_MODIFICATION` | Resource was modified since client's last read |
| 410 | `GONE` | Resource has been permanently removed (deprecated endpoints) |
| 422 | `VALIDATION_FAILED` | Request body failed schema validation |
| 422 | `BUNDLE_VALIDATION_FAILED` | Bundle content is semantically invalid |
| 422 | `EDGE_TYPE_UNKNOWN` | Referenced edge type does not exist |
| 422 | `NAMESPACE_NOT_FOUND` | Referenced namespace does not exist |
| 422 | `TEMP_ID_UNRESOLVED` | Edge references a temp_id not in the bundle |
| 429 | `RATE_LIMITED` | Too many requests |
| 500 | `INTERNAL_ERROR` | Server-side failure |
| 502 | `UPSTREAM_ERROR` | Dependency (database, extension) failed |
| 503 | `SERVICE_UNAVAILABLE` | Server is temporarily unable to handle requests |

### 5.3 Validation Error Details

Validation errors (422) include structured details for each field:

```json
{
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "Request validation failed",
    "details": [
      {
        "field": "claims[0].content",
        "code": "REQUIRED",
        "message": "Content is required"
      },
      {
        "field": "claims[1].claim_type",
        "code": "PATTERN",
        "message": "Must match pattern ^[a-z_]+$"
      },
      {
        "field": "edges[0].target_temp_id",
        "code": "UNRESOLVED_REFERENCE",
        "message": "temp_id 'c99' not found in bundle claims"
      }
    ],
    "request_id": "req-uuid"
  }
}
```

### 5.4 Rate Limit Error Details

Rate limit errors (429) include retry guidance:

```json
{
  "error": {
    "code": "RATE_LIMITED",
    "message": "Request rate limit exceeded",
    "details": {
      "limit": 100,
      "window_seconds": 60,
      "current_usage": 105,
      "retry_after_seconds": 23
    },
    "request_id": "req-uuid"
  }
}
```

The `Retry-After` header is also set with the number of seconds to wait.

---

## 6. Rate Limiting Strategy

### 6.1 Rate Limit Tiers

| Tier | Read Requests | Write Requests | Use Case |
|------|---------------|----------------|----------|
| **Standard** | 1000/min | 100/min | Default for new extensions |
| **Elevated** | 5000/min | 500/min | Vetted extensions with higher volume |
| **Unlimited** | No limit | 1000/min | First-party extensions, admin |

Writes are always rate-limited even for unlimited tier to prevent runaway ingestion.

### 6.2 Rate Limit Headers

Every response includes rate limit headers:

```
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 847
X-RateLimit-Reset: 1707393600
X-RateLimit-Window: 60
```

### 6.3 Rate Limit Scope

Rate limits are applied per API key. Different endpoints may have different limits:

| Endpoint Category | Standard Limit | Notes |
|-------------------|----------------|-------|
| `GET /v1/claims/*` | 1000/min | Read operations |
| `POST /v1/query/*` | 500/min | Search is more expensive |
| `POST /v1/bundles` | 100/min | Write operations |
| `POST /v1/ingest` | 20/min | Triggers async processing |
| `WS /v1/subscribe` | 10 concurrent | WebSocket connections |

### 6.4 Burst Handling

The rate limiter uses a sliding window algorithm with burst allowance:

- **Window**: 60 seconds
- **Burst**: 20% above limit for 10 seconds
- **Backoff**: After burst, strict limit for remainder of window

This allows legitimate traffic spikes while preventing abuse.

### 6.5 Exemptions

Health check endpoints (`/health`, `/ready`) are never rate-limited.

---

## 7. Webhook System

### 7.1 Event Types

The backend emits events for significant state changes. Extensions and external systems can subscribe to receive webhooks.

| Event Type | Trigger | Payload |
|------------|---------|---------|
| `claim_created` | New claim committed | Claim ID, content, type, bundle ID |
| `claim_updated` | Claim version created | Old and new claim IDs, diff |
| `claim_retracted` | Claim marked retracted | Claim ID, retraction reason |
| `bundle_accepted` | Bundle successfully committed | Bundle ID, claim/edge/artifact counts |
| `bundle_rejected` | Bundle failed validation | Bundle idempotency key, errors |
| `evidence_linked` | New evidential edge created | Source ID, target ID, relationship |
| `pending_reference_resolved` | External ref matched to claim | External ref, resolved claim ID |
| `ingestion_completed` | Async ingestion job finished | Job ID, source ID, bundle ID |
| `ingestion_failed` | Async ingestion job failed | Job ID, error details |

### 7.2 Webhook Registration

```
POST /v1/webhooks
```

**Request Body:**

```json
{
  "url": "https://my-extension.example.com/webhook",
  "event_types": ["claim_created", "bundle_accepted"],
  "filters": {
    "namespace_prefix": "biology",
    "extension_id": "ext-paper-ingest-v2"
  },
  "secret": "whsec_abc123..."
}
```

**Required scope:** `webhooks:manage`

**Response:** `201 Created`

```json
{
  "webhook_id": "wh-uuid",
  "url": "https://my-extension.example.com/webhook",
  "event_types": ["claim_created", "bundle_accepted"],
  "status": "active",
  "created_at": "2026-02-08T10:00:00Z"
}
```

### 7.3 Webhook Delivery

Webhooks are delivered as POST requests with JSON bodies:

```json
{
  "event_id": "evt-uuid",
  "event_type": "claim_created",
  "timestamp": "2026-02-08T10:30:00Z",
  "data": {
    "claim_id": "claim-uuid",
    "content": "Compound X reduces inflammation by 40%",
    "claim_type": "empirical",
    "bundle_id": "bundle-uuid",
    "namespace": "biology.immunology"
  }
}
```

**Headers:**

```
Content-Type: application/json
X-Webhook-ID: wh-uuid
X-Event-ID: evt-uuid
X-Event-Type: claim_created
X-Timestamp: 1707393600
X-Signature: sha256=abc123...
```

### 7.4 Signature Verification

Webhooks are signed using HMAC-SHA256 with the secret provided during registration:

```python
import hmac
import hashlib

def verify_webhook(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)
```

### 7.5 Retry Policy

Failed deliveries (non-2xx response or timeout) are retried with exponential backoff:

- **Attempt 1**: Immediate
- **Attempt 2**: 30 seconds
- **Attempt 3**: 2 minutes
- **Attempt 4**: 10 minutes
- **Attempt 5**: 1 hour

After 5 failed attempts, the webhook is marked `failing`. After 24 hours of continuous failure, it is marked `disabled`. Webhook owners receive an email (if configured) when status changes.

### 7.6 Webhook Management

```
GET /v1/webhooks                    # List webhooks
GET /v1/webhooks/{webhook_id}       # Get webhook details
PATCH /v1/webhooks/{webhook_id}     # Update webhook
DELETE /v1/webhooks/{webhook_id}    # Delete webhook
POST /v1/webhooks/{webhook_id}/test # Send test event
GET /v1/webhooks/{webhook_id}/deliveries  # List recent deliveries
```

---

## 8. GraphQL Considerations

### 8.1 Decision: Deferred to v2

GraphQL is **not included in v1**. The decision is explicit and intentional.

### 8.2 Rationale for Deferral

**Why GraphQL is attractive for this project:**
- The knowledge graph structure maps naturally to GraphQL's graph query model.
- Clients could request exactly the fields and relationships they need, reducing over-fetching.
- Nested queries (`claim → evidence → evidence.provenance`) would be cleaner than multiple REST calls.

**Why we're deferring:**

1. **Complexity budget.** v1 is about proving the core concept works. Adding GraphQL doubles the API surface area to maintain, document, and version.

2. **Extension simplicity.** Extensions use the REST API. GraphQL adds cognitive load for extension developers. REST is universally understood; GraphQL requires learning a query language.

3. **Caching.** REST responses with proper `ETag` and `Cache-Control` headers are trivially cacheable. GraphQL caching (persisted queries, response normalization) adds infrastructure complexity.

4. **Rate limiting.** GraphQL's flexible queries make rate limiting harder — a single query can request arbitrary depth of relationships. REST endpoints have predictable cost.

5. **Performance predictability.** Deep nested GraphQL queries can trigger expensive database traversals. REST endpoints are designed with specific query patterns and indexes in mind.

### 8.3 v2 GraphQL Plan

When GraphQL is added in v2:

- It will be a **read-only** layer on top of the existing services. Mutations will remain REST-only for auditability and simplicity.
- Schema will be auto-generated from Pydantic models using `strawberry-graphql`.
- Depth and complexity limits will be enforced to prevent expensive queries.
- Persisted queries will be required in production to prevent arbitrary query injection.
- GraphQL will be available at `/v2/graphql` alongside the REST API, not as a replacement.

---

## 9. Extension API

### 9.1 Extension Registration

Extensions register to receive API credentials and declare their capabilities.

```
POST /v1/extensions/register
```

**Request Body:** Extension manifest (see `extension-protocol.md` Section 4).

**Required scope:** `extensions:write` or admin API key.

**Response:** `201 Created`

```json
{
  "extension_id": "ext-my-input-v1",
  "api_key": "ext_key_live_abc123...",
  "status": "active",
  "scopes": ["bundles:write", "claims:read", "search:read"],
  "registered_at": "2026-02-08T10:00:00Z"
}
```

The API key is shown exactly once. Store it securely.

### 9.2 Extension Discovery

```
GET /v1/extensions
```

Lists registered extensions for client discovery.

**Query Parameters:**
- `type` (string, optional): Filter by `input` or `output`.
- `status` (string, optional): Filter by `active`, `degraded`, `inactive`.
- `verified` (bool, optional): Only show verified extensions.
- `capability` (string, optional): Filter by capability (e.g., `claim_types=empirical`).

**Response:** `200 OK`

```json
{
  "extensions": [
    {
      "extension_id": "ext-paper-ingest-v2",
      "name": "Paper Ingestion",
      "version": "2.0.0",
      "type": "input",
      "description": "Extracts claims from academic papers",
      "status": "active",
      "verified": true,
      "capabilities": {
        "claim_types": ["empirical", "mechanistic"],
        "creates_artifacts": true
      }
    }
  ]
}
```

### 9.3 Extension Management

```
GET /v1/extensions/{extension_id}       # Get extension details
PATCH /v1/extensions/{extension_id}     # Update manifest
DELETE /v1/extensions/{extension_id}    # Deregister (revokes API key)
POST /v1/extensions/{extension_id}/rotate-key  # Rotate API key
```

### 9.4 Extension Health

Extensions that declare a `health_check_url` are pinged by the backend.

```
GET /v1/extensions/{extension_id}/health
```

**Response:** `200 OK`

```json
{
  "extension_id": "ext-paper-ingest-v2",
  "status": "healthy",
  "last_check": "2026-02-08T10:29:00Z",
  "uptime_seconds": 86400,
  "consecutive_failures": 0
}
```

### 9.5 Extension Event Subscriptions

Extensions can subscribe to backend events via WebSocket for real-time composition.

```
WS /v1/subscribe
```

**Connection:**
```
wss://api.newpublishing.example.com/v1/subscribe?token=ext_key_live_abc123...
```

**Subscribe message:**
```json
{
  "action": "subscribe",
  "event_types": ["claim_created", "pending_reference_resolved"],
  "filters": {"namespace_prefix": "biology"}
}
```

**Event message:**
```json
{
  "event_id": "evt-uuid",
  "event_type": "claim_created",
  "timestamp": "2026-02-08T10:30:00Z",
  "data": {...}
}
```

**Heartbeat:** The server sends a `ping` frame every 30 seconds. Clients must respond with `pong` or be disconnected.

### 9.6 Extension Calling Core APIs

Extensions use the same REST API as any client, authenticated with their API key. The SDK provides a typed client wrapper:

```python
from newpublishing.extensions.client import NewPublishingClient

client = NewPublishingClient(
    base_url="https://api.newpublishing.example.com",
    api_key="ext_key_live_abc123...",
)

# Submit bundle
response = await client.submit_bundle(result, source, idempotency_key, contributor_id)

# Search
results = await client.search("compound X inflammation", top_k=20)

# Traverse
graph = await client.traverse(start=claim_uuid, depth=3)

# Get claim
claim = await client.get_claim(claim_uuid)
```

The client handles:
- Authentication headers
- Request/response serialization
- Error translation to typed exceptions
- Automatic retry with exponential backoff
- Rate limit handling (waits and retries on 429)

---

## 10. OpenAPI Specification

The API is fully documented via OpenAPI 3.1. The specification is auto-generated from FastAPI route definitions and Pydantic schemas.

### 10.1 Accessing the Spec

```
GET /openapi.json    # JSON format
GET /docs            # Swagger UI
GET /redoc           # ReDoc UI
```

### 10.2 Code Generation

Clients can generate SDKs from the OpenAPI spec:

```bash
# TypeScript
npx openapi-generator-cli generate -i https://api.newpublishing.example.com/openapi.json -g typescript-fetch -o ./client

# Python
openapi-python-client generate --url https://api.newpublishing.example.com/openapi.json
```

The official Python SDK (`newpublishing-sdk`) is hand-written with async/await support and is the recommended client for Python extensions.

### 10.3 Schema Versioning

The OpenAPI spec includes the API version:

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "NewPublishing Knowledge Backend",
    "version": "1.0.0"
  }
}
```

Breaking changes increment the major version. The spec at `/openapi.json` always reflects the latest supported version. Historical specs are available at `/v1/openapi.json`, `/v2/openapi.json`, etc.

---

## Appendix A: Endpoint Summary

| Method | Endpoint | Purpose | Scope Required |
|--------|----------|---------|----------------|
| `POST` | `/v1/bundles` | Submit knowledge bundle | `bundles:write` |
| `GET` | `/v1/bundles/{id}` | Get bundle metadata | `claims:read` |
| `GET` | `/v1/claims` | List claims | `claims:read` |
| `GET` | `/v1/claims/{id}` | Get claim by ID | `claims:read` |
| `PATCH` | `/v1/claims/{id}` | Update claim (new version) | `claims:write` |
| `DELETE` | `/v1/claims/{id}` | Retract claim | `claims:write` |
| `GET` | `/v1/claims/{id}/evidence` | Get evidence for claim | `claims:read` |
| `POST` | `/v1/claims/{id}/evidence` | Link evidence | `bundles:write` |
| `GET` | `/v1/claims/{id}/confidence` | Get computed confidence | `claims:read` |
| `GET` | `/v1/claims/{id}/confidence/distribution` | Get confidence distribution | `claims:read` |
| `POST` | `/v1/ingest` | Trigger ingestion job | `bundles:write` |
| `GET` | `/v1/ingest/{job_id}` | Get ingestion status | `claims:read` |
| `POST` | `/v1/query/search` | Semantic search | `search:read` |
| `POST` | `/v1/query/traverse` | Graph traversal | `search:read` |
| `POST` | `/v1/query/view` | Specialized views | `search:read` |
| `POST` | `/v1/extensions/register` | Register extension | `extensions:write` |
| `GET` | `/v1/extensions` | List extensions | `extensions:read` |
| `GET` | `/v1/extensions/{id}` | Get extension details | `extensions:read` |
| `PATCH` | `/v1/extensions/{id}` | Update extension | `extensions:write` |
| `DELETE` | `/v1/extensions/{id}` | Deregister extension | `extensions:write` |
| `POST` | `/v1/extensions/{id}/rotate-key` | Rotate API key | `extensions:write` |
| `GET` | `/v1/extensions/{id}/health` | Get extension health | `extensions:read` |
| `POST` | `/v1/webhooks` | Create webhook | `webhooks:manage` |
| `GET` | `/v1/webhooks` | List webhooks | `webhooks:manage` |
| `GET` | `/v1/webhooks/{id}` | Get webhook details | `webhooks:manage` |
| `PATCH` | `/v1/webhooks/{id}` | Update webhook | `webhooks:manage` |
| `DELETE` | `/v1/webhooks/{id}` | Delete webhook | `webhooks:manage` |
| `POST` | `/v1/webhooks/{id}/test` | Send test event | `webhooks:manage` |
| `GET` | `/v1/webhooks/{id}/deliveries` | List deliveries | `webhooks:manage` |
| `WS` | `/v1/subscribe` | Event subscription | `search:read` |
| `GET` | `/health` | Health check | None |
| `GET` | `/ready` | Readiness check | None |
| `GET` | `/openapi.json` | OpenAPI spec | None |
| `GET` | `/docs` | Swagger UI | None |

---

## Appendix B: Implementation Notes

### B.1 Database Query Patterns

**Claim retrieval** uses the `claims_latest` view for latest-only queries:
```sql
SELECT * FROM claims_latest WHERE namespace LIKE 'biology.%';
```

**Confidence computation** uses the `claims_with_confidence` view which aggregates reviews.

**Graph traversal** uses recursive CTEs with depth limiting:
```sql
WITH RECURSIVE graph AS (
    SELECT c.id, 0 AS depth FROM claims c WHERE c.id = $1
    UNION ALL
    SELECT e.target_id, g.depth + 1
    FROM graph g
    JOIN edges e ON e.source_id = g.id
    WHERE g.depth < $2
)
SELECT DISTINCT id FROM graph;
```

**Semantic search** uses pgvector's approximate nearest neighbor:
```sql
SELECT id, content, embedding <=> $1 AS distance
FROM claims
WHERE embedding <=> $1 < $2
ORDER BY embedding <=> $1
LIMIT $3;
```

### B.2 Embedding Generation

Claims are embedded at ingestion time. The embedding service:
1. Concatenates `content` + `formal_content` (if present)
2. Truncates to 8192 tokens (model limit)
3. Calls OpenAI `text-embedding-3-small`
4. Stores the 1536-dimensional vector in `claims.embedding`

Embedding generation is synchronous within bundle commit. If the embedding service is unavailable, the bundle is rejected.

### B.3 Idempotency

Bundle submission is idempotent. The `idempotency_key` is unique per extension:
- Same key + same content → returns cached response
- Same key + different content → returns `409 IDEMPOTENCY_CONFLICT`
- Idempotency records expire after 7 days

This allows safe retries after network failures.

### B.4 Transaction Boundaries

Bundle commit is a single database transaction:
1. Insert source
2. Insert claims (with generated UUIDs)
3. Resolve temp_ids to UUIDs
4. Insert edges
5. Insert artifacts
6. Link artifacts to claims
7. Create pending references for external_refs
8. Insert bundle record
9. Commit

If any step fails, the entire transaction rolls back. The client can retry with the same idempotency key.

---

## Appendix C: Future Considerations

### C.1 Multi-Tenancy (v2)

v1 is single-tenant. v2 will add:
- Tenant isolation at the namespace level
- Tenant-specific API keys and rate limits
- Cross-tenant claim sharing with explicit grants

### C.2 Batch Operations (v2)

For high-volume clients:
```
POST /v2/claims/batch-get
POST /v2/query/batch-search
```

### C.3 Streaming Responses (v2)

For large result sets:
```
GET /v2/claims?stream=true
Accept: application/x-ndjson
```

### C.4 Audit Log API (v2)

For compliance and debugging:
```
GET /v2/audit/events?actor={agent_id}&after={timestamp}
```