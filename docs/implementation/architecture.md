# Phiacta Architecture Plan

*Implementation blueprint for the knowledge backend. Read `docs/design/synthesis.md` for the schema design and rationale that this document builds on.*

---

## 1. Language Choice: Python 3.12+ with FastAPI

### Decision

Python 3.12+ as the primary language. FastAPI as the web framework. SQLAlchemy 2.0 as the ORM. Pydantic v2 for data validation and serialization.

### Rationale

**Why Python over Rust, Go, or TypeScript:**

- **AI/ML ecosystem alignment.** The paper ingestion extension, claim extraction, and embedding generation all depend heavily on the Python ML ecosystem (transformers, sentence-transformers, LangChain/LlamaIndex, OpenAI SDK). Writing the backend in Python means extensions share the same runtime and can import core models directly. A Rust or Go backend would force every AI-powered extension to bridge languages or run as a separate service.

- **Extension developer reach.** The project lives or dies on third-party extension adoption. Python has the largest pool of scientific computing developers (the target audience). A researcher who can write a Jupyter notebook can write an extension. Rust or Go would dramatically shrink the contributor pool.

- **FastAPI specifically.** FastAPI provides automatic OpenAPI documentation, native async support, Pydantic-based request/response validation, and WebSocket support out of the box. These map directly to our API requirements: versioned REST endpoints, structured query payloads, event subscriptions, and auto-generated API docs for extension developers. Django and Flask were considered but lack native async and automatic schema generation.

- **SQLAlchemy 2.0 specifically.** The 2.0-style query API uses type-annotated models, supports async via `asyncio`, and integrates cleanly with Pydantic for serialization. Tortoise ORM and Django ORM were considered but have weaker typing and less mature async stories.

- **Performance is not the bottleneck for v1.** The critical path is AI claim extraction (seconds per paper), not HTTP request handling. Python's per-request overhead is negligible compared to LLM inference. If raw query throughput becomes a bottleneck at scale, the hot paths (graph traversal, embedding search) are handled by PostgreSQL and pgvector, not Python. We can also add a Rust-based query accelerator as a sidecar later without rewriting the core.

### Python Version

Python 3.12+ is required. Key features used:

- `type` statement for type aliases (3.12)
- Improved error messages (3.12)
- Performance improvements in the interpreter (3.11+, 3.12+)
- `tomllib` in stdlib for config parsing (3.11+)

### Typing Policy

All code uses strict type annotations. `mypy --strict` is enforced in CI. This is non-negotiable for a project that serves as a platform for third-party extensions -- extension developers need reliable type information to build against.

---

## 2. Project Structure

```
phiacta/
├── pyproject.toml                    # Project metadata, dependencies, tool config
├── alembic.ini                       # Database migration config
├── docker-compose.yml                # Local dev: postgres + backend + workers
├── Dockerfile                        # Multi-stage build for the backend
├── CLAUDE.md                         # AI assistant context
├── LICENSE                           # GPL-3.0
├── README.md
│
├── src/
│   └── phiacta/
│       ├── __init__.py
│       ├── main.py                   # FastAPI app factory, lifespan, middleware
│       ├── config.py                 # Settings via pydantic-settings (env vars)
│       │
│       ├── models/                   # SQLAlchemy ORM models (source of truth)
│       │   ├── __init__.py
│       │   ├── base.py              # DeclarativeBase, common mixins (UUIDMixin, TimestampMixin)
│       │   ├── agent.py             # Agent model
│       │   ├── namespace.py         # Namespace model (hierarchical)
│       │   ├── source.py            # Source model
│       │   ├── claim.py             # Claim model (versioning, embedding, attrs)
│       │   ├── edge.py              # Edge + EdgeType models
│       │   ├── provenance.py        # Provenance model
│       │   ├── review.py            # Review model
│       │   ├── bundle.py            # Bundle model (atomic submission tracking)
│       │   ├── artifact.py          # Artifact model (figures, tables, photos)
│       │   └── pending_reference.py # PendingReference model (cross-bundle resolution)
│       │
│       ├── schemas/                  # Pydantic schemas (API request/response shapes)
│       │   ├── __init__.py
│       │   ├── claims.py            # ClaimCreate, ClaimRead, ClaimUpdate, ClaimListParams
│       │   ├── bundles.py           # BundleSubmit, BundleResponse, BundleWarning
│       │   ├── queries.py           # SearchRequest, TraverseRequest, ViewRequest
│       │   ├── agents.py            # AgentCreate, AgentRead
│       │   ├── reviews.py           # ReviewCreate, ReviewRead
│       │   ├── sources.py           # SourceCreate, SourceRead
│       │   ├── extensions.py        # ExtensionManifest, ExtensionRegistration
│       │   └── common.py            # Pagination, ErrorResponse, shared types
│       │
│       ├── api/                      # FastAPI routers (thin layer: validate, delegate, respond)
│       │   ├── __init__.py
│       │   ├── deps.py              # Dependency injection (db session, auth, current agent)
│       │   ├── v1/
│       │   │   ├── __init__.py      # v1 router aggregation
│       │   │   ├── bundles.py       # POST /v1/bundles
│       │   │   ├── claims.py        # GET /v1/claims/{id}, GET /v1/claims, PATCH /v1/claims/{id}
│       │   │   ├── query.py         # POST /v1/query/search, /traverse, /view
│       │   │   ├── agents.py        # Agent CRUD
│       │   │   ├── reviews.py       # Review CRUD
│       │   │   ├── extensions.py    # Extension registration, discovery
│       │   │   └── subscriptions.py # WebSocket /v1/subscribe
│       │   └── health.py            # GET /health, GET /ready
│       │
│       ├── services/                 # Business logic (stateless, testable)
│       │   ├── __init__.py
│       │   ├── bundle_service.py    # Bundle validation pipeline, atomic commit
│       │   ├── claim_service.py     # Claim CRUD, versioning, lineage resolution
│       │   ├── search_service.py    # Semantic search (embedding + pgvector)
│       │   ├── traversal_service.py # Graph traversal (recursive CTE queries)
│       │   ├── view_service.py      # View rendering (paper, proof tree, comparison)
│       │   ├── embedding_service.py # Embedding generation (calls external model)
│       │   ├── event_service.py     # Event emission for subscriptions
│       │   └── duplicate_service.py # Duplicate detection via embedding similarity
│       │
│       ├── extensions/               # Extension protocol base classes
│       │   ├── __init__.py
│       │   ├── base.py             # InputExtension, OutputExtension ABCs
│       │   ├── registry.py         # Extension registration, discovery, health checks
│       │   └── auth.py             # Extension API key management, permission scoping
│       │
│       └── db/                       # Database utilities
│           ├── __init__.py
│           ├── session.py           # Async session factory, engine config
│           └── migrations/          # Alembic migration scripts
│               ├── env.py
│               └── versions/
│
├── extensions/                       # Built-in extensions (each is a standalone package)
│   ├── paper_ingestion/
│   │   ├── __init__.py
│   │   ├── extension.py            # PaperIngestionExtension(InputExtension)
│   │   ├── pdf_parser.py           # PDF text/figure/table extraction
│   │   ├── claim_extractor.py      # LLM-based claim extraction
│   │   └── citation_resolver.py    # DOI/reference resolution
│   ├── search/
│   │   ├── __init__.py
│   │   ├── extension.py            # SearchExtension(OutputExtension)
│   │   └── ranking.py              # Result ranking strategies
│   └── manual_entry/
│       ├── __init__.py
│       └── extension.py            # ManualEntryExtension(InputExtension)
│
├── tests/
│   ├── conftest.py                  # Fixtures: test db, async client, factory functions
│   ├── unit/
│   │   ├── test_bundle_service.py
│   │   ├── test_claim_service.py
│   │   ├── test_traversal_service.py
│   │   └── test_models.py
│   ├── integration/
│   │   ├── test_bundle_api.py
│   │   ├── test_claim_api.py
│   │   ├── test_search_api.py
│   │   └── test_traversal_api.py
│   └── extensions/
│       ├── test_paper_ingestion.py
│       └── test_search.py
│
└── docs/
    ├── design/                      # Existing design docs
    ├── implementation/              # This document and future impl docs
    └── extensions/                  # Extension developer guide (1-page quickstart)
```

### Key Structural Decisions

**`src/` layout with `pyproject.toml`.** The `src/phiacta/` layout prevents accidental imports of the local directory during development and is the modern Python packaging standard. The project is installable via `pip install -e .` for local dev.

**Models vs. Schemas separation.** SQLAlchemy models (`models/`) define database structure. Pydantic schemas (`schemas/`) define API shapes. These are intentionally separate because:
- API responses often include computed fields not in the database (e.g., `epistemic_status`).
- API inputs need validation rules that don't belong on the ORM model.
- Extensions see schemas, not models. This is the API contract boundary.

**Services layer.** All business logic lives in `services/`. API routes are thin: validate input (Pydantic handles this), call the appropriate service, return the result. Services are stateless functions that take a database session and parameters. This makes them independently testable without HTTP overhead.

**Built-in extensions as separate packages.** Extensions under `extensions/` follow the same protocol as third-party extensions. They import from `phiacta.extensions.base` and submit bundles through the API. This dogfooding ensures the extension protocol is actually usable.

---

## 3. Dependencies

### Core Backend

| Package | Version | Purpose |
|---------|---------|---------|
| `fastapi` | >=0.115 | Web framework, OpenAPI generation |
| `uvicorn[standard]` | >=0.32 | ASGI server (with uvloop + httptools) |
| `pydantic` | >=2.9 | Data validation, settings, schemas |
| `pydantic-settings` | >=2.6 | Environment-based configuration |
| `sqlalchemy[asyncio]` | >=2.0.36 | ORM with async support |
| `asyncpg` | >=0.30 | Async PostgreSQL driver (fastest for Python) |
| `alembic` | >=1.14 | Database migrations |
| `pgvector` | >=0.3 | Python bindings for pgvector (SQLAlchemy integration) |
| `python-jose[cryptography]` | >=3.3 | JWT token handling for auth |
| `passlib[bcrypt]` | >=1.7 | API key hashing |
| `websockets` | >=14.0 | WebSocket support for event subscriptions |
| `httpx` | >=0.28 | Async HTTP client (extension health checks, webhook calls) |
| `tenacity` | >=9.0 | Retry logic for external service calls |
| `structlog` | >=24.4 | Structured logging (JSON output for production) |

### AI/ML (used by embedding service and built-in extensions)

| Package | Version | Purpose |
|---------|---------|---------|
| `openai` | >=1.58 | Embedding generation (text-embedding-3-small/large) |
| `tiktoken` | >=0.8 | Token counting for embedding chunking |

### Development

| Package | Version | Purpose |
|---------|---------|---------|
| `pytest` | >=8.3 | Testing framework |
| `pytest-asyncio` | >=0.24 | Async test support |
| `pytest-cov` | >=6.0 | Coverage reporting |
| `httpx` | >=0.28 | Async test client (also a runtime dep) |
| `factory-boy` | >=3.3 | Test data factories |
| `mypy` | >=1.13 | Static type checking |
| `ruff` | >=0.8 | Linting + formatting (replaces black, isort, flake8) |
| `pre-commit` | >=4.0 | Git hooks for lint/type checks |

### Built-in Extension Dependencies (paper ingestion)

| Package | Version | Purpose |
|---------|---------|---------|
| `pymupdf` | >=1.25 | PDF text and image extraction |
| `openai` | >=1.58 | LLM-based claim extraction |

### What's NOT included (and why)

- **No Celery / task queue for v1.** Bundle processing is synchronous within the request. If a bundle takes >30s (unlikely for v1 scale), we add a background worker later. Premature async infrastructure adds operational complexity with no v1 benefit.
- **No Redis for v1.** WebSocket subscriptions use in-process pubsub. Event fan-out via Redis Pub/Sub is a scaling concern for later.
- **No LangChain / LlamaIndex.** Direct OpenAI SDK calls are simpler and more predictable for the two operations we need (embeddings, claim extraction). These frameworks add abstraction without value at this stage.
- **No Kafka / RabbitMQ.** Event-driven composition between extensions uses WebSocket subscriptions for v1. Message brokers are a scaling concern.

---

## 4. Database Setup: PostgreSQL 16 + pgvector

### Why PostgreSQL 16

- **pgvector 0.7+** for vector similarity search (IVFFlat and HNSW indexes).
- **JSONB with GIN indexes** for querying `attrs` metadata (e.g., `WHERE attrs->>'p_value' < '0.05'`).
- **Recursive CTEs** for bounded-depth graph traversal.
- **ACID transactions** for atomic bundle commits.
- Mature replication, backup, and monitoring ecosystem.

### Schema Deployment

The DDL from `docs/design/schema-proposal.md` is the baseline. Alembic manages migrations from that point forward.

**Initial migration creates:**

1. The 8 core tables from the schema proposal: `agents`, `namespaces`, `sources`, `claims`, `edge_types`, `edges`, `provenance`, `reviews`.
2. The 3 additional tables identified in synthesis.md section 7: `artifacts`, `pending_references`, `bundles`.
3. All indexes from the DDL (B-tree, IVFFlat for embeddings, GIN for full-text search and JSONB).
4. The seed data for the 15 initial edge types.
5. The two views: `claims_latest` and `claims_with_confidence`.

### Additional Tables (beyond schema-proposal.md)

**`bundles`** -- tracks atomic submissions:

```sql
CREATE TABLE bundles (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    idempotency_key TEXT NOT NULL UNIQUE,
    submitted_by   UUID NOT NULL REFERENCES agents(id),
    extension_id   TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'accepted'
                   CHECK (status IN ('accepted', 'rejected', 'processing')),
    claim_count    INT NOT NULL DEFAULT 0,
    edge_count     INT NOT NULL DEFAULT 0,
    artifact_count INT NOT NULL DEFAULT 0,
    submitted_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    attrs          JSONB NOT NULL DEFAULT '{}'
);
```

**`artifacts`** -- figures, tables, photos linked to claims:

```sql
CREATE TABLE artifacts (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    bundle_id       UUID REFERENCES bundles(id),
    artifact_type   TEXT NOT NULL,
    description     TEXT,
    storage_ref     TEXT,
    content_inline  TEXT,
    structured_data JSONB,
    attrs           JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE artifact_claims (
    artifact_id UUID NOT NULL REFERENCES artifacts(id),
    claim_id    UUID NOT NULL REFERENCES claims(id),
    PRIMARY KEY (artifact_id, claim_id)
);
```

**`pending_references`** -- cross-bundle resolution:

```sql
CREATE TABLE pending_references (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_claim_id UUID NOT NULL REFERENCES claims(id),
    external_ref    TEXT NOT NULL,
    edge_type       TEXT NOT NULL REFERENCES edge_types(name),
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'resolved', 'expired')),
    resolved_to     UUID REFERENCES claims(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ
);

CREATE INDEX idx_pending_refs_external ON pending_references(external_ref)
    WHERE status = 'pending';
```

### Connection Configuration

```python
# config.py (via pydantic-settings, all from environment variables)
DATABASE_URL = "postgresql+asyncpg://newpub:password@localhost:5432/phiacta"
DATABASE_POOL_SIZE = 20        # max concurrent connections
DATABASE_MAX_OVERFLOW = 10     # burst capacity
DATABASE_POOL_TIMEOUT = 30     # seconds to wait for a connection
```

### Embedding Index Strategy

The IVFFlat index from the schema DDL (`idx_claims_embedding`) requires a training step after data is loaded. For initial deployment:

1. Start with no vector index (exact search). This is fine for <10K claims.
2. After 10K+ claims, create the IVFFlat index with `lists = sqrt(num_claims)`.
3. At 1M+ claims, evaluate HNSW index for better recall at the cost of more memory.

The embedding dimension is 1536 (OpenAI `text-embedding-3-small`). If we switch to a different model, a migration changes the vector dimension.

---

## 5. Extension Base Classes

The extension protocol is the most important API surface in the project. Extensions must be trivial to write, well-typed, and impossible to misuse.

### Design Principles

1. **Extensions are standalone processes.** They communicate with the backend exclusively via HTTP/WebSocket. They do not import backend internals. They CAN import the base classes and schema types from a published `phiacta-sdk` package.
2. **Base classes define the contract, not the implementation.** `InputExtension` says "you must implement `ingest()`." It does not dictate how you parse PDFs or transcribe audio.
3. **The SDK is a thin wrapper.** It handles auth, HTTP client setup, bundle submission, and error handling. Extension developers focus only on their domain logic.

### Base Class Definitions

```python
# phiacta/extensions/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass
class Source:
    """A real-world artifact that knowledge was extracted from."""
    source_type: str                    # 'paper', 'recording', 'photo', etc.
    title: str | None = None
    external_ref: str | None = None     # DOI, URL, file path
    content_hash: str | None = None     # SHA-256 of source artifact
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractedClaim:
    """A claim extracted by an input extension, ready for bundle submission."""
    temp_id: str                        # Extension-assigned ID within the bundle
    content: str                        # Human-readable statement
    claim_type: str                     # 'assertion', 'theorem', 'observation', etc.
    confidence: float | None = None     # Extraction confidence (0.0-1.0)
    formal_content: str | None = None   # Machine-verifiable (Lean, etc.)
    namespace: str | None = None        # Target namespace name or ID
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractedEdge:
    """A relationship extracted by an input extension."""
    source_temp_id: str                 # References an ExtractedClaim.temp_id
    target_temp_id: str | None = None   # References an ExtractedClaim.temp_id
    target_id: UUID | None = None       # References an existing claim by ID
    target_external_ref: str | None = None  # Pending reference (DOI, URL)
    edge_type: str                      # 'supports', 'depends_on', etc.
    strength: float | None = None       # 0.0-1.0
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractedArtifact:
    """An artifact (figure, table, photo) extracted by an input extension."""
    temp_id: str
    artifact_type: str                  # 'figure', 'table', 'photo', etc.
    description: str | None = None
    storage_ref: str | None = None      # URI to blob storage
    content_inline: str | None = None   # For small artifacts stored directly
    structured_data: dict[str, Any] | None = None
    linked_claim_temp_ids: list[str] = field(default_factory=list)


@dataclass
class ExtractionResult:
    """The output of an input extension's ingest() method."""
    claims: list[ExtractedClaim]
    edges: list[ExtractedEdge] = field(default_factory=list)
    artifacts: list[ExtractedArtifact] = field(default_factory=list)


@dataclass
class QueryRequest:
    """A structured query from a consumer."""
    query: str                          # Natural language query
    top_k: int = 20
    filters: dict[str, Any] = field(default_factory=dict)
    include: list[str] = field(default_factory=list)


@dataclass
class QueryResponse:
    """The output of an output extension's query() method."""
    results: list[dict[str, Any]]
    total_matches: int
    metadata: dict[str, Any] = field(default_factory=dict)


class InputExtension(ABC):
    """
    Base class for extensions that add knowledge to the backend.

    Subclass this and implement `ingest()`. The SDK handles authentication,
    bundle construction, submission, and error handling.

    Example:
        class PaperIngestion(InputExtension):
            name = "paper-ingestion"
            version = "1.0.0"

            async def ingest(self, source: Source) -> ExtractionResult:
                pdf_text = parse_pdf(source.external_ref)
                claims = extract_claims(pdf_text)
                return ExtractionResult(claims=claims)
    """

    name: str                           # Unique extension identifier
    version: str                        # Semver
    description: str = ""

    @abstractmethod
    async def ingest(self, source: Source) -> ExtractionResult:
        """
        Extract structured knowledge from a source.

        Args:
            source: The real-world artifact to process.

        Returns:
            ExtractionResult containing claims, edges, and artifacts
            extracted from the source.
        """
        ...

    async def validate(self, result: ExtractionResult) -> list[str]:
        """
        Optional: validate extraction results before submission.
        Returns a list of warning messages (empty list = all good).
        Override to add extension-specific validation.
        """
        return []


class OutputExtension(ABC):
    """
    Base class for extensions that query and present knowledge.

    Subclass this and implement `query()`. The SDK handles authentication
    and backend communication.

    Example:
        class SearchExtension(OutputExtension):
            name = "search"
            version = "1.0.0"

            async def query(self, request: QueryRequest) -> QueryResponse:
                results = await self.backend.search(request.query, top_k=request.top_k)
                return QueryResponse(results=results, total_matches=len(results))
    """

    name: str
    version: str
    description: str = ""

    @abstractmethod
    async def query(self, request: QueryRequest) -> QueryResponse:
        """
        Query the knowledge backend and return structured results.

        Args:
            request: The query parameters.

        Returns:
            QueryResponse with results and metadata.
        """
        ...
```

### SDK Client (shipped with the base classes)

Extensions don't call the REST API directly. They use a client that wraps the HTTP calls:

```python
# phiacta/extensions/client.py

class PhiactaClient:
    """HTTP client for extensions to communicate with the backend."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key

    async def submit_bundle(
        self,
        result: ExtractionResult,
        source: Source,
        idempotency_key: str,
        contributor_id: str,
    ) -> BundleResponse: ...

    async def search(self, query: str, top_k: int = 20, **filters) -> list[dict]: ...

    async def get_claim(self, claim_id: UUID) -> dict: ...

    async def traverse(self, start: UUID, depth: int = 2, **kwargs) -> dict: ...

    async def subscribe(self, event_types: list[str], **filters) -> AsyncIterator[dict]: ...
```

### What Writing an Extension Looks Like

A complete input extension in ~30 lines:

```python
from phiacta.extensions.base import InputExtension, Source, ExtractionResult, ExtractedClaim

class ManualEntry(InputExtension):
    name = "manual-entry"
    version = "1.0.0"
    description = "Manually enter claims via a form"

    async def ingest(self, source: Source) -> ExtractionResult:
        # source.attrs contains the form data
        return ExtractionResult(
            claims=[
                ExtractedClaim(
                    temp_id="c1",
                    content=source.attrs["content"],
                    claim_type=source.attrs.get("claim_type", "assertion"),
                    confidence=1.0,  # Human-entered = full extraction confidence
                )
            ]
        )
```

---

## 6. Docker and Containerization

### Local Development: `docker-compose.yml`

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: phiacta
      POSTGRES_USER: newpub
      POSTGRES_PASSWORD: devpassword
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U newpub -d phiacta"]
      interval: 5s
      timeout: 5s
      retries: 5

  backend:
    build:
      context: .
      dockerfile: Dockerfile
      target: development
    environment:
      DATABASE_URL: "postgresql+asyncpg://newpub:devpassword@db:5432/phiacta"
      OPENAI_API_KEY: "${OPENAI_API_KEY}"
      LOG_LEVEL: "debug"
      ENVIRONMENT: "development"
    ports:
      - "8000:8000"
    volumes:
      - ./src:/app/src
      - ./extensions:/app/extensions
    depends_on:
      db:
        condition: service_healthy
    command: >
      uvicorn phiacta.main:app
      --host 0.0.0.0
      --port 8000
      --reload
      --reload-dir /app/src

volumes:
  pgdata:
```

### Dockerfile (multi-stage)

```dockerfile
# Stage 1: Base with dependencies
FROM python:3.12-slim AS base
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml .
RUN uv pip install --system --no-cache -e ".[all]"

# Stage 2: Development (with hot reload, source mounted)
FROM base AS development
COPY . .
RUN uv pip install --system --no-cache -e ".[dev]"
EXPOSE 8000

# Stage 3: Production (minimal, no dev deps)
FROM base AS production
COPY src/ src/
COPY extensions/ extensions/
COPY alembic.ini .
RUN uv pip install --system --no-cache -e .
EXPOSE 8000
CMD ["uvicorn", "phiacta.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

### Startup Sequence

`docker compose up` triggers this sequence:

1. **PostgreSQL starts** and passes health check (`pg_isready`).
2. **Backend starts** and runs Alembic migrations on boot (via lifespan hook in `main.py`).
3. **Alembic creates tables** if they don't exist, including pgvector extension, all 11 tables, indexes, views, and seed data for edge types.
4. **Backend binds to port 8000.** API docs available at `http://localhost:8000/docs`.

The startup is idempotent. Running `docker compose up` on an existing database with data is safe -- Alembic only runs pending migrations.

### Production Deployment

For production Kubernetes deployments, the approach is:

1. **PostgreSQL**: Use a managed service (AWS RDS, GCP Cloud SQL, or self-hosted with the `pgvector/pgvector` image). Do NOT run PostgreSQL in a container in production unless you have a strong ops story for backups and failover.
2. **Backend**: Deploy the `production` stage of the Dockerfile. Run with `--workers N` where N = 2 * CPU cores. Put behind a reverse proxy (nginx, Caddy, or cloud load balancer) for TLS termination.
3. **Migrations**: Run as a Kubernetes Job or init container before the backend starts. Never auto-migrate in production.
4. **Config**: All configuration via environment variables. No config files, no secrets in images.

A Helm chart is planned but not part of v1. The `docker-compose.yml` is the primary deployment artifact for early adopters.

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | -- | PostgreSQL connection string |
| `OPENAI_API_KEY` | Yes | -- | For embedding generation |
| `ENVIRONMENT` | No | `production` | `development` or `production` |
| `LOG_LEVEL` | No | `info` | `debug`, `info`, `warning`, `error` |
| `CORS_ORIGINS` | No | `[]` | Allowed CORS origins (JSON array) |
| `API_KEY_SALT` | No | (generated) | Salt for API key hashing |
| `EMBEDDING_MODEL` | No | `text-embedding-3-small` | OpenAI embedding model name |
| `EMBEDDING_DIMENSIONS` | No | `1536` | Must match vector column dimension |
| `MAX_BUNDLE_CLAIMS` | No | `500` | Max claims per bundle submission |
| `MAX_TRAVERSAL_DEPTH` | No | `10` | Max depth for graph traversal queries |

---

## 7. API Versioning Strategy

All routes are prefixed with `/v1/`. When breaking changes are needed:

1. New routes go under `/v2/`. Both versions are served simultaneously.
2. `/v1/` continues to work for at least 6 months after `/v2/` launches.
3. Extensions declare which API version they require in their manifest. The backend validates compatibility.
4. Deprecation warnings are returned as HTTP headers: `Deprecation: true`, `Sunset: <date>`.

Non-breaking changes (new optional fields, new endpoints) are added to the current version without a version bump.

---

## 8. Authentication and Authorization

### For v1: API Key Authentication

Simple API key auth. No OAuth, no SSO. These are v2 concerns.

- Extensions register and receive an API key.
- The key is sent in the `Authorization: Bearer <key>` header.
- Keys are hashed (bcrypt) and stored in the database. Raw keys are shown once at creation.
- Each key has scopes: `bundles:write`, `claims:read`, `claims:write`, `admin`.
- Rate limiting is per-key, enforced in middleware.

### User Identity

For v1, contributor identity is a simple string (`contributor_id`) passed by the extension. The backend records it in provenance but does not authenticate users directly. Extensions are responsible for authenticating their users.

Full user auth (JWT, OAuth2) is a v2 feature when multi-tenancy and access control become necessary.

---

## 9. Error Handling

All errors return a consistent JSON structure:

```json
{
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "Human-readable summary",
    "details": [...],
    "request_id": "uuid"
  }
}
```

Error codes and HTTP status mapping follow the spec in `extension-design.md` section 6.10. FastAPI exception handlers translate Python exceptions to this format.

Services raise domain exceptions (`BundleValidationError`, `ClaimNotFoundError`, etc.). The API layer catches these and maps to HTTP responses. Services never return HTTP status codes.

---

## 10. Testing Strategy

### Three Layers

1. **Unit tests** (`tests/unit/`): Test services in isolation. Mock the database session. Fast, run in <10s.
2. **Integration tests** (`tests/integration/`): Test API routes against a real PostgreSQL instance (via `docker compose`). Use `httpx.AsyncClient` with the FastAPI test client. Each test runs in a transaction that is rolled back.
3. **Extension tests** (`tests/extensions/`): Test built-in extensions end-to-end. Submit bundles via the API, verify the database state.

### CI Pipeline

```
ruff check + ruff format --check  →  mypy --strict  →  pytest (unit)  →  pytest (integration, needs postgres)
```

All four steps must pass before merge. Integration tests spin up a PostgreSQL container in CI.

---

## 11. Implementation Order

Based on the critical path from `synthesis.md` section 6:

| Phase | What | Why |
|-------|------|-----|
| **Phase 1** | Database + models + migrations | Foundation. Nothing works without the schema. |
| **Phase 2** | Bundle submission API (`POST /v1/bundles`) | The write path. Extensions need this to submit knowledge. |
| **Phase 3** | Claim retrieval API (`GET /v1/claims`) | The read path. Basic verification that data is stored correctly. |
| **Phase 4** | Paper ingestion extension | The critical test. If AI can't extract claims from papers, stop here. |
| **Phase 5** | Semantic search (`POST /v1/query/search`) | Demonstrate value: "what is known about X?" |
| **Phase 6** | Graph traversal (`POST /v1/query/traverse`) | Evidence chains, dependency analysis. |
| **Phase 7** | Extension base classes + SDK packaging | Enable third-party development. |
| **Phase 8** | WebSocket subscriptions, views, remaining API | Full API surface. |

Phase 4 is the make-or-break moment. The synthesis document is explicit: if paper ingestion doesn't work well enough, pause and wait for AI to improve. Don't build infrastructure for an empty database.
