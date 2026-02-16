# Phiacta Implementation Plan

*Actionable roadmap for building the knowledge backend. Total estimated time: 11-15 days.*

*Prerequisites: Read `docs/design/synthesis.md` for schema rationale and `docs/implementation/architecture.md` for technical decisions.*

---

## Overview

This plan implements a **claim-centric knowledge graph** backed by PostgreSQL + pgvector. The architecture follows the critical path identified in the design phase:

```
Schema + Database → Paper Ingestion Extension → Search/Query → Everything Else
```

The paper ingestion extension is the make-or-break moment. If AI cannot reliably extract claims from papers, the project pauses. Do not build infrastructure for an empty database.

### Time Estimates

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| **Phase 0: Project Setup** | 0.5 day | None |
| **Phase 1: Core Data Layer** | 2-3 days | Phase 0 |
| **Phase 2: API Layer** | 2 days | Phase 1 |
| **Phase 3: Knowledge Graph** | 2-3 days | Phase 2 |
| **Phase 4: Extension System** | 2-3 days | Phase 2 |
| **Phase 5: Production Ready** | 2 days | Phases 3, 4 |

**Total: 11-15 days** for a deployable system with paper ingestion.

---

## Phase 0: Project Setup (0.5 day)

### Objective

Establish the development environment, tooling, and CI pipeline. Every subsequent phase builds on this foundation.

### 0.1 Project Initialization

Create the repository structure:

```
phiacta/
├── pyproject.toml
├── alembic.ini
├── docker-compose.yml
├── Dockerfile
├── .pre-commit-config.yaml
├── .github/
│   └── workflows/
│       └── ci.yml
├── CLAUDE.md
├── README.md
├── src/
│   └── phiacta/
│       ├── __init__.py
│       ├── main.py
│       └── config.py
├── tests/
│   └── conftest.py
└── docs/
    └── (existing design docs)
```

### 0.2 pyproject.toml

```toml
[project]
name = "phiacta"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    # Web framework
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    
    # Database
    "sqlalchemy[asyncio]>=2.0.36",
    "asyncpg>=0.30",
    "alembic>=1.14",
    "pgvector>=0.3",
    
    # Auth
    "python-jose[cryptography]>=3.3",
    "passlib[bcrypt]>=1.7",
    
    # HTTP / WebSocket
    "websockets>=14.0",
    "httpx>=0.28",
    "tenacity>=9.0",
    
    # Logging
    "structlog>=24.4",
    
    # AI/ML
    "openai>=1.58",
    "tiktoken>=0.8",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pytest-cov>=6.0",
    "factory-boy>=3.3",
    "mypy>=1.13",
    "ruff>=0.8",
    "pre-commit>=4.0",
]
extensions = [
    "pymupdf>=1.25",  # PDF parsing for paper ingestion
]
all = ["phiacta[dev,extensions]"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "A", "C4", "PT", "RUF"]

[tool.mypy]
python_version = "3.12"
strict = true
plugins = ["pydantic.mypy"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

### 0.3 Pre-commit Configuration

`.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.13.0
    hooks:
      - id: mypy
        additional_dependencies:
          - pydantic>=2.9
          - sqlalchemy>=2.0.36
        args: [--strict, src/]
```

### 0.4 GitHub Actions CI

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install ruff
      - run: ruff check .
      - run: ruff format --check .

  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: mypy --strict src/

  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_DB: test_phiacta
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: pytest --cov=src/ --cov-report=term-missing
        env:
          DATABASE_URL: postgresql+asyncpg://test:test@localhost:5432/test_phiacta
```

### 0.5 Docker Development Environment

`docker-compose.yml` and `Dockerfile` as specified in `deployment.md`. The multi-stage Dockerfile provides:
- `development` target with hot reload
- `test` target for CI
- `production` target for deployment

### 0.6 Initial Application Skeleton

`src/phiacta/config.py`:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    openai_api_key: str
    environment: str = "production"
    log_level: str = "info"
    log_format: str = "json"
    cors_origins: list[str] = []
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    database_pool_size: int = 20
    max_bundle_claims: int = 500
    max_traversal_depth: int = 10

    class Config:
        env_file = ".env"

settings = Settings()
```

`src/phiacta/main.py`:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from phiacta.config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: run migrations in dev mode
    if settings.environment == "development":
        from alembic import command
        from alembic.config import Config
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
    yield
    # Shutdown: cleanup

app = FastAPI(
    title="Phiacta Knowledge Backend",
    version="0.1.0",
    lifespan=lifespan,
)

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/ready")
async def ready():
    # TODO: Check database connectivity
    return {"status": "ready"}
```

### Files Created in Phase 0

| File | Purpose |
|------|---------|
| `pyproject.toml` | Project metadata, dependencies, tool config |
| `.pre-commit-config.yaml` | Git hooks for lint/format/typecheck |
| `.github/workflows/ci.yml` | CI pipeline |
| `docker-compose.yml` | Local development stack |
| `Dockerfile` | Multi-stage container build |
| `alembic.ini` | Migration configuration |
| `src/phiacta/__init__.py` | Package marker |
| `src/phiacta/config.py` | Settings via pydantic-settings |
| `src/phiacta/main.py` | FastAPI app factory |
| `tests/conftest.py` | Pytest fixtures |
| `CLAUDE.md` | AI assistant context |
| `README.md` | Project documentation |

### Success Criteria

- [ ] `docker compose up` starts PostgreSQL + backend
- [ ] `curl localhost:8000/health` returns 200
- [ ] `ruff check .` passes
- [ ] `mypy --strict src/` passes
- [ ] `pytest` runs (even if no tests yet)
- [ ] GitHub Actions CI completes successfully

### Risk: Pre-commit hook setup issues

**Mitigation:** Test `pre-commit run --all-files` before committing. Add troubleshooting notes to README.

---

## Phase 1: Core Data Layer (2-3 days)

### Objective

Implement SQLAlchemy models for all 11 tables, create the initial Alembic migration, and establish the repository pattern for data access.

### 1.1 SQLAlchemy Base and Mixins

`src/phiacta/models/base.py`:

```python
from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class UUIDMixin:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )
```

### 1.2 Core Models (11 Tables)

Create models according to the schema in `synthesis.md`:

| Model | File | Key Fields |
|-------|------|------------|
| `Agent` | `models/agent.py` | `id`, `agent_type`, `name`, `trust_score`, `attrs` |
| `Namespace` | `models/namespace.py` | `id`, `name`, `parent_id`, `description` |
| `Source` | `models/source.py` | `id`, `source_type`, `title`, `external_ref`, `content_hash` |
| `Claim` | `models/claim.py` | `id`, `lineage_id`, `version`, `content`, `claim_type`, `embedding`, `attrs` |
| `EdgeType` | `models/edge.py` | `name`, `category`, `transitive`, `symmetric`, `description` |
| `Edge` | `models/edge.py` | `id`, `source_id`, `target_id`, `edge_type`, `asserted_by`, `strength` |
| `Provenance` | `models/provenance.py` | `id`, `claim_id`, `source_id`, `extraction_confidence`, `location` |
| `Review` | `models/review.py` | `id`, `claim_id`, `agent_id`, `confidence`, `assessment` |
| `Bundle` | `models/bundle.py` | `id`, `idempotency_key`, `submitted_by`, `extension_id`, `status` |
| `Artifact` | `models/artifact.py` | `id`, `bundle_id`, `artifact_type`, `storage_ref`, `structured_data` |
| `PendingReference` | `models/pending_reference.py` | `id`, `source_claim_id`, `external_ref`, `status`, `resolved_to` |

### 1.3 Claim Model Detail

The Claim model is the most complex. Key implementation notes:

```python
# models/claim.py
from pgvector.sqlalchemy import Vector
from sqlalchemy import Index, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR

class Claim(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "claims"
    
    lineage_id: Mapped[UUID] = mapped_column(index=True)
    version: Mapped[int] = mapped_column(default=1)
    content: Mapped[str]
    claim_type: Mapped[str]
    namespace_id: Mapped[UUID | None] = mapped_column(ForeignKey("namespaces.id"))
    formal_content: Mapped[str | None]
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    search_tsv: Mapped[str | None] = mapped_column(TSVECTOR)
    attrs: Mapped[dict] = mapped_column(JSONB, default=dict)
    
    # Relationships
    namespace: Mapped["Namespace"] = relationship(back_populates="claims")
    outgoing_edges: Mapped[list["Edge"]] = relationship(
        foreign_keys="Edge.source_id", back_populates="source_claim"
    )
    incoming_edges: Mapped[list["Edge"]] = relationship(
        foreign_keys="Edge.target_id", back_populates="target_claim"
    )
    provenance_records: Mapped[list["Provenance"]] = relationship(back_populates="claim")
    reviews: Mapped[list["Review"]] = relationship(back_populates="claim")

# Indexes
Index("idx_claims_embedding", Claim.embedding, postgresql_using="ivfflat")
Index("idx_claims_search_tsv", Claim.search_tsv, postgresql_using="gin")
Index("idx_claims_attrs", Claim.attrs, postgresql_using="gin")
```

### 1.4 Initial Alembic Migration

Generate after models are complete:

```bash
alembic revision --autogenerate -m "initial_schema"
```

The migration must:
1. Enable `uuid-ossp` and `vector` PostgreSQL extensions
2. Create all 11 tables with relationships
3. Create all indexes (B-tree, IVFFlat, GIN)
4. Seed the 15 initial edge types
5. Create views: `claims_latest`, `claims_with_confidence`

**EdgeType seed data:**

```python
# In the migration's upgrade() function
edge_types = [
    # Evidential
    {"name": "supports", "category": "evidential", "transitive": False, "symmetric": False},
    {"name": "contradicts", "category": "evidential", "transitive": False, "symmetric": True},
    {"name": "corroborates", "category": "evidential", "transitive": False, "symmetric": True},
    # Logical
    {"name": "depends_on", "category": "logical", "transitive": True, "symmetric": False},
    {"name": "assumes", "category": "logical", "transitive": False, "symmetric": False},
    {"name": "derives_from", "category": "logical", "transitive": True, "symmetric": False},
    {"name": "implies", "category": "logical", "transitive": True, "symmetric": False},
    {"name": "equivalent_to", "category": "logical", "transitive": True, "symmetric": True},
    # Structural
    {"name": "generalizes", "category": "structural", "transitive": True, "symmetric": False},
    {"name": "refines", "category": "structural", "transitive": True, "symmetric": False},
    {"name": "part_of", "category": "structural", "transitive": True, "symmetric": False},
    {"name": "instantiates", "category": "structural", "transitive": False, "symmetric": False},
    # Editorial
    {"name": "supersedes", "category": "editorial", "transitive": True, "symmetric": False},
    {"name": "related_to", "category": "editorial", "transitive": False, "symmetric": True},
    {"name": "responds_to", "category": "editorial", "transitive": False, "symmetric": False},
]
```

### 1.5 Database Session Management

`src/phiacta/db/session.py`:

```python
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from phiacta.config import settings

engine = create_async_engine(
    settings.database_url,
    pool_size=settings.database_pool_size,
    max_overflow=10,
    pool_timeout=30,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def get_db() -> AsyncSession:
    async with async_session_factory() as session:
        yield session
```

### 1.6 Repository Pattern

Create repositories for clean data access:

```python
# src/phiacta/repositories/claim_repository.py
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from phiacta.models.claim import Claim

class ClaimRepository:
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_by_id(self, claim_id: UUID) -> Claim | None:
        return await self.session.get(Claim, claim_id)
    
    async def get_by_lineage(self, lineage_id: UUID) -> list[Claim]:
        result = await self.session.execute(
            select(Claim)
            .where(Claim.lineage_id == lineage_id)
            .order_by(Claim.version.desc())
        )
        return list(result.scalars().all())
    
    async def get_latest_version(self, lineage_id: UUID) -> Claim | None:
        result = await self.session.execute(
            select(Claim)
            .where(Claim.lineage_id == lineage_id)
            .order_by(Claim.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
    
    async def create(self, claim: Claim) -> Claim:
        self.session.add(claim)
        await self.session.flush()
        return claim
```

### 1.7 Basic CRUD Tests

`tests/unit/test_models.py`:

```python
import pytest
from uuid import uuid4
from phiacta.models.claim import Claim

@pytest.fixture
def sample_claim():
    lineage_id = uuid4()
    return Claim(
        lineage_id=lineage_id,
        version=1,
        content="Test claim content",
        claim_type="assertion",
    )

def test_claim_defaults(sample_claim):
    assert sample_claim.version == 1
    assert sample_claim.claim_type == "assertion"
    assert sample_claim.attrs == {}
```

`tests/integration/test_claim_repository.py`:

```python
import pytest
from uuid import uuid4

@pytest.mark.asyncio
async def test_create_and_get_claim(db_session, claim_factory):
    claim = await claim_factory.create(content="Integration test claim")
    
    from phiacta.repositories.claim_repository import ClaimRepository
    repo = ClaimRepository(db_session)
    
    retrieved = await repo.get_by_id(claim.id)
    assert retrieved is not None
    assert retrieved.content == "Integration test claim"
```

### Files Created in Phase 1

| File | Purpose |
|------|---------|
| `src/phiacta/models/__init__.py` | Model exports |
| `src/phiacta/models/base.py` | DeclarativeBase, mixins |
| `src/phiacta/models/agent.py` | Agent model |
| `src/phiacta/models/namespace.py` | Namespace model |
| `src/phiacta/models/source.py` | Source model |
| `src/phiacta/models/claim.py` | Claim model with embedding |
| `src/phiacta/models/edge.py` | Edge + EdgeType models |
| `src/phiacta/models/provenance.py` | Provenance model |
| `src/phiacta/models/review.py` | Review model |
| `src/phiacta/models/bundle.py` | Bundle model |
| `src/phiacta/models/artifact.py` | Artifact + ArtifactClaim |
| `src/phiacta/models/pending_reference.py` | PendingReference model |
| `src/phiacta/db/__init__.py` | DB utilities package |
| `src/phiacta/db/session.py` | Async session factory |
| `src/phiacta/db/migrations/env.py` | Alembic environment |
| `src/phiacta/db/migrations/versions/001_initial.py` | Initial schema |
| `src/phiacta/repositories/__init__.py` | Repository exports |
| `src/phiacta/repositories/claim_repository.py` | Claim CRUD |
| `src/phiacta/repositories/agent_repository.py` | Agent CRUD |
| `src/phiacta/repositories/bundle_repository.py` | Bundle CRUD |
| `tests/unit/test_models.py` | Model unit tests |
| `tests/integration/test_claim_repository.py` | Repository integration tests |
| `tests/conftest.py` | Fixtures: test DB, factories |

### Success Criteria

- [ ] `alembic upgrade head` creates all 11 tables
- [ ] `alembic downgrade base` cleanly removes them
- [ ] EdgeType seed data includes all 15 types
- [ ] pgvector extension is enabled (test: `SELECT * FROM pg_extension WHERE extname = 'vector'`)
- [ ] All model relationships load correctly (test with eager loading)
- [ ] Repository tests pass against real PostgreSQL
- [ ] `mypy --strict` passes on all model files

### Risk: pgvector version mismatch

**Mitigation:** Pin `pgvector/pgvector:pg16` in docker-compose. Document the required PostgreSQL + pgvector versions in README.

### Risk: Complex migration autogeneration failures

**Mitigation:** Review every autogenerated migration manually. Alembic misses some changes (constraint renames, index modifications). Add explicit `op.execute()` for pgvector extension and seed data.

---

## Phase 2: API Layer (2 days)

### Objective

Implement FastAPI routes for bundle submission and claim retrieval. This is the write path (ingestion) and read path (basic queries).

### 2.1 Pydantic Schemas

`src/phiacta/schemas/claims.py`:

```python
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field

class ClaimBase(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    claim_type: str
    formal_content: str | None = None
    namespace_id: UUID | None = None
    attrs: dict = Field(default_factory=dict)

class ClaimCreate(ClaimBase):
    pass

class ClaimRead(ClaimBase):
    id: UUID
    lineage_id: UUID
    version: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class ClaimListParams(BaseModel):
    limit: int = Field(default=20, le=100)
    offset: int = Field(default=0, ge=0)
    claim_type: str | None = None
    namespace_id: UUID | None = None
```

`src/phiacta/schemas/bundles.py`:

```python
from uuid import UUID
from pydantic import BaseModel, Field

class SourceInput(BaseModel):
    source_type: str
    title: str | None = None
    external_ref: str | None = None
    content_hash: str | None = None
    attrs: dict = Field(default_factory=dict)

class ClaimInput(BaseModel):
    temp_id: str
    content: str
    claim_type: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    formal_content: str | None = None
    namespace: str | None = None
    attrs: dict = Field(default_factory=dict)

class EdgeInput(BaseModel):
    source_temp_id: str
    target_temp_id: str | None = None
    target_id: UUID | None = None
    target_external_ref: str | None = None
    edge_type: str
    strength: float | None = Field(default=None, ge=0.0, le=1.0)
    attrs: dict = Field(default_factory=dict)

class ArtifactInput(BaseModel):
    temp_id: str
    artifact_type: str
    description: str | None = None
    storage_ref: str | None = None
    content_inline: str | None = None
    structured_data: dict | None = None
    linked_claim_temp_ids: list[str] = Field(default_factory=list)

class BundleSubmit(BaseModel):
    idempotency_key: str = Field(..., min_length=1, max_length=256)
    source: SourceInput
    claims: list[ClaimInput] = Field(..., min_length=1)
    edges: list[EdgeInput] = Field(default_factory=list)
    artifacts: list[ArtifactInput] = Field(default_factory=list)
    contributor_id: str

class BundleResponse(BaseModel):
    bundle_id: UUID
    status: str  # "accepted" | "rejected"
    created_claims: list[UUID]
    created_edges: int
    created_artifacts: int
    warnings: list[str]
```

### 2.2 Dependency Injection

`src/phiacta/api/deps.py`:

```python
from typing import Annotated
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from phiacta.db.session import get_db
from phiacta.models.agent import Agent
from phiacta.services.auth_service import verify_api_key

async def get_current_agent(
    authorization: Annotated[str, Header()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Agent:
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header",
        )
    api_key = authorization[7:]
    agent = await verify_api_key(db, api_key)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return agent

DBSession = Annotated[AsyncSession, Depends(get_db)]
CurrentAgent = Annotated[Agent, Depends(get_current_agent)]
```

### 2.3 Bundle Service

`src/phiacta/services/bundle_service.py`:

```python
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from phiacta.models import Claim, Edge, Source, Bundle, Provenance
from phiacta.schemas.bundles import BundleSubmit, BundleResponse
from phiacta.services.embedding_service import generate_embedding

class BundleService:
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def submit(
        self,
        bundle: BundleSubmit,
        agent_id: UUID,
        extension_id: str,
    ) -> BundleResponse:
        # Check idempotency
        existing = await self._get_by_idempotency_key(bundle.idempotency_key)
        if existing:
            return self._bundle_to_response(existing)
        
        # Validate bundle
        warnings = self._validate(bundle)
        
        # Create source
        source = await self._create_source(bundle.source)
        
        # Map temp_id -> UUID
        temp_to_uuid: dict[str, UUID] = {}
        created_claims: list[UUID] = []
        
        # Create claims
        for claim_input in bundle.claims:
            claim = await self._create_claim(claim_input, source.id, agent_id)
            temp_to_uuid[claim_input.temp_id] = claim.id
            created_claims.append(claim.id)
        
        # Create edges
        edge_count = 0
        for edge_input in bundle.edges:
            await self._create_edge(edge_input, temp_to_uuid, agent_id)
            edge_count += 1
        
        # Create artifacts
        artifact_count = await self._create_artifacts(bundle.artifacts, temp_to_uuid)
        
        # Create bundle record
        bundle_record = Bundle(
            idempotency_key=bundle.idempotency_key,
            submitted_by=agent_id,
            extension_id=extension_id,
            status="accepted",
            claim_count=len(created_claims),
            edge_count=edge_count,
            artifact_count=artifact_count,
        )
        self.session.add(bundle_record)
        await self.session.commit()
        
        return BundleResponse(
            bundle_id=bundle_record.id,
            status="accepted",
            created_claims=created_claims,
            created_edges=edge_count,
            created_artifacts=artifact_count,
            warnings=warnings,
        )
    
    async def _create_claim(
        self,
        claim_input: ClaimInput,
        source_id: UUID,
        agent_id: UUID,
    ) -> Claim:
        lineage_id = uuid4()
        embedding = await generate_embedding(claim_input.content)
        
        claim = Claim(
            lineage_id=lineage_id,
            version=1,
            content=claim_input.content,
            claim_type=claim_input.claim_type,
            embedding=embedding,
            formal_content=claim_input.formal_content,
            attrs=claim_input.attrs,
        )
        self.session.add(claim)
        await self.session.flush()
        
        # Create provenance
        provenance = Provenance(
            claim_id=claim.id,
            source_id=source_id,
            extraction_confidence=claim_input.confidence,
        )
        self.session.add(provenance)
        
        return claim
```

### 2.4 API Routes

`src/phiacta/api/v1/bundles.py`:

```python
from fastapi import APIRouter, HTTPException, status
from phiacta.api.deps import DBSession, CurrentAgent
from phiacta.schemas.bundles import BundleSubmit, BundleResponse
from phiacta.services.bundle_service import BundleService

router = APIRouter(prefix="/bundles", tags=["bundles"])

@router.post("", response_model=BundleResponse, status_code=status.HTTP_201_CREATED)
async def submit_bundle(
    bundle: BundleSubmit,
    db: DBSession,
    agent: CurrentAgent,
):
    service = BundleService(db)
    try:
        return await service.submit(
            bundle=bundle,
            agent_id=agent.id,
            extension_id=agent.name,  # Extension name as ID
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
```

`src/phiacta/api/v1/claims.py`:

```python
from uuid import UUID
from fastapi import APIRouter, HTTPException, status
from phiacta.api.deps import DBSession, CurrentAgent
from phiacta.schemas.claims import ClaimRead, ClaimListParams
from phiacta.repositories.claim_repository import ClaimRepository

router = APIRouter(prefix="/claims", tags=["claims"])

@router.get("/{claim_id}", response_model=ClaimRead)
async def get_claim(claim_id: UUID, db: DBSession, agent: CurrentAgent):
    repo = ClaimRepository(db)
    claim = await repo.get_by_id(claim_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    return claim

@router.get("", response_model=list[ClaimRead])
async def list_claims(
    db: DBSession,
    agent: CurrentAgent,
    params: ClaimListParams = Depends(),
):
    repo = ClaimRepository(db)
    return await repo.list(
        limit=params.limit,
        offset=params.offset,
        claim_type=params.claim_type,
        namespace_id=params.namespace_id,
    )
```

### 2.5 Router Aggregation

`src/phiacta/api/v1/__init__.py`:

```python
from fastapi import APIRouter
from phiacta.api.v1 import bundles, claims, agents, reviews

router = APIRouter(prefix="/v1")
router.include_router(bundles.router)
router.include_router(claims.router)
router.include_router(agents.router)
router.include_router(reviews.router)
```

Update `main.py`:

```python
from phiacta.api.v1 import router as v1_router

app.include_router(v1_router)
```

### 2.6 Auth Middleware (API Keys)

`src/phiacta/services/auth_service.py`:

```python
from uuid import UUID
from passlib.hash import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from phiacta.models.agent import Agent

async def verify_api_key(session: AsyncSession, api_key: str) -> Agent | None:
    # API keys are stored as bcrypt hashes
    # Format: ext_key_<env>_<random>
    result = await session.execute(select(Agent))
    for agent in result.scalars():
        if agent.api_key_hash and bcrypt.verify(api_key, agent.api_key_hash):
            return agent
    return None

def generate_api_key(agent_name: str) -> tuple[str, str]:
    """Returns (raw_key, hashed_key)"""
    import secrets
    raw = f"ext_key_live_{secrets.token_urlsafe(32)}"
    hashed = bcrypt.hash(raw)
    return raw, hashed
```

### 2.7 OpenAPI Documentation

FastAPI auto-generates OpenAPI docs. Enhance with docstrings and response models. Access at `/docs` (Swagger UI) or `/redoc`.

### Files Created in Phase 2

| File | Purpose |
|------|---------|
| `src/phiacta/schemas/__init__.py` | Schema exports |
| `src/phiacta/schemas/claims.py` | Claim schemas |
| `src/phiacta/schemas/bundles.py` | Bundle schemas |
| `src/phiacta/schemas/agents.py` | Agent schemas |
| `src/phiacta/schemas/reviews.py` | Review schemas |
| `src/phiacta/schemas/common.py` | Pagination, errors |
| `src/phiacta/api/__init__.py` | API package |
| `src/phiacta/api/deps.py` | Dependency injection |
| `src/phiacta/api/v1/__init__.py` | v1 router aggregation |
| `src/phiacta/api/v1/bundles.py` | Bundle endpoints |
| `src/phiacta/api/v1/claims.py` | Claim endpoints |
| `src/phiacta/api/v1/agents.py` | Agent endpoints |
| `src/phiacta/api/v1/reviews.py` | Review endpoints |
| `src/phiacta/api/health.py` | Health/ready endpoints |
| `src/phiacta/services/__init__.py` | Service exports |
| `src/phiacta/services/bundle_service.py` | Bundle processing |
| `src/phiacta/services/claim_service.py` | Claim operations |
| `src/phiacta/services/auth_service.py` | API key verification |
| `src/phiacta/services/embedding_service.py` | OpenAI embeddings |
| `tests/integration/test_bundle_api.py` | Bundle API tests |
| `tests/integration/test_claim_api.py` | Claim API tests |

### Success Criteria

- [ ] `POST /v1/bundles` accepts a bundle and returns created claim IDs
- [ ] `GET /v1/claims/{id}` returns the claim
- [ ] Idempotency key prevents duplicate bundle submissions
- [ ] Invalid API key returns 401
- [ ] OpenAPI docs are complete at `/docs`
- [ ] All endpoints have integration tests
- [ ] Embeddings are generated via OpenAI API

### Risk: OpenAI API rate limits during high ingestion

**Mitigation:** Implement client-side rate limiting with exponential backoff (via `tenacity`). For bulk ingestion, batch embedding requests (OpenAI supports up to 2048 texts per request).

---

## Phase 3: Knowledge Graph (2-3 days)

### Objective

Implement semantic search (pgvector), graph traversal (recursive CTEs), and the confidence computation pipeline.

### 3.1 Semantic Search Service

`src/phiacta/services/search_service.py`:

```python
from uuid import UUID
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from phiacta.models.claim import Claim
from phiacta.services.embedding_service import generate_embedding

class SearchService:
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def semantic_search(
        self,
        query: str,
        top_k: int = 20,
        claim_types: list[str] | None = None,
        namespace_id: UUID | None = None,
    ) -> list[dict]:
        # Generate query embedding
        query_embedding = await generate_embedding(query)
        
        # Build the query with pgvector cosine distance
        sql = """
            SELECT 
                c.id,
                c.content,
                c.claim_type,
                c.created_at,
                1 - (c.embedding <=> :embedding) as similarity
            FROM claims c
            WHERE c.embedding IS NOT NULL
        """
        params = {"embedding": query_embedding, "top_k": top_k}
        
        if claim_types:
            sql += " AND c.claim_type = ANY(:claim_types)"
            params["claim_types"] = claim_types
        
        if namespace_id:
            sql += " AND c.namespace_id = :namespace_id"
            params["namespace_id"] = str(namespace_id)
        
        sql += " ORDER BY c.embedding <=> :embedding LIMIT :top_k"
        
        result = await self.session.execute(text(sql), params)
        return [
            {
                "id": str(row.id),
                "content": row.content,
                "claim_type": row.claim_type,
                "created_at": row.created_at.isoformat(),
                "similarity": float(row.similarity),
            }
            for row in result
        ]
```

### 3.2 Graph Traversal Service

`src/phiacta/services/traversal_service.py`:

```python
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

class TraversalService:
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def traverse(
        self,
        start_id: UUID,
        depth: int = 2,
        edge_types: list[str] | None = None,
        direction: str = "both",  # "outgoing", "incoming", "both"
    ) -> dict:
        """
        Traverse the claim graph from a starting node.
        Uses recursive CTE for bounded-depth traversal.
        """
        edge_filter = ""
        if edge_types:
            edge_filter = f"AND e.edge_type = ANY(ARRAY{edge_types})"
        
        direction_filter = ""
        if direction == "outgoing":
            direction_filter = "AND e.source_id = g.claim_id"
        elif direction == "incoming":
            direction_filter = "AND e.target_id = g.claim_id"
        
        sql = f"""
            WITH RECURSIVE graph AS (
                -- Base case: starting node
                SELECT 
                    :start_id::uuid as claim_id,
                    0 as depth,
                    ARRAY[:start_id::uuid] as path
                
                UNION ALL
                
                -- Recursive case: traverse edges
                SELECT 
                    CASE 
                        WHEN e.source_id = g.claim_id THEN e.target_id
                        ELSE e.source_id
                    END as claim_id,
                    g.depth + 1,
                    g.path || CASE 
                        WHEN e.source_id = g.claim_id THEN e.target_id
                        ELSE e.source_id
                    END
                FROM graph g
                JOIN edges e ON (e.source_id = g.claim_id OR e.target_id = g.claim_id)
                    {edge_filter}
                    {direction_filter}
                WHERE g.depth < :max_depth
                    AND NOT (CASE 
                        WHEN e.source_id = g.claim_id THEN e.target_id
                        ELSE e.source_id
                    END = ANY(g.path))  -- Prevent cycles
            )
            SELECT DISTINCT ON (g.claim_id)
                g.claim_id,
                g.depth,
                c.content,
                c.claim_type
            FROM graph g
            JOIN claims c ON c.id = g.claim_id
            ORDER BY g.claim_id, g.depth
        """
        
        result = await self.session.execute(
            text(sql),
            {"start_id": str(start_id), "max_depth": depth}
        )
        
        nodes = {}
        for row in result:
            nodes[str(row.claim_id)] = {
                "id": str(row.claim_id),
                "depth": row.depth,
                "content": row.content,
                "claim_type": row.claim_type,
            }
        
        # Fetch edges between traversed nodes
        edges = await self._get_edges_between(list(nodes.keys()))
        
        return {
            "start_id": str(start_id),
            "max_depth": depth,
            "nodes": list(nodes.values()),
            "edges": edges,
        }
    
    async def get_evidence_chain(self, claim_id: UUID) -> list[dict]:
        """Get the chain of supporting evidence for a claim."""
        return await self.traverse(
            start_id=claim_id,
            depth=5,
            edge_types=["supports", "corroborates", "derives_from"],
            direction="incoming",
        )
    
    async def get_dependents(self, claim_id: UUID) -> list[dict]:
        """Get claims that depend on this claim."""
        return await self.traverse(
            start_id=claim_id,
            depth=3,
            edge_types=["depends_on", "assumes", "derives_from"],
            direction="outgoing",
        )
```

### 3.3 Confidence Propagation

`src/phiacta/services/confidence_service.py`:

```python
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from phiacta.models.review import Review
from phiacta.models.agent import Agent

class ConfidenceService:
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def compute_confidence(
        self,
        claim_id: UUID,
        trust_weights: dict[str, float] | None = None,
    ) -> dict:
        """
        Compute aggregated confidence for a claim from reviewer assessments.
        
        Confidence is perspectival: different consumers can apply different
        trust models. This method computes a weighted average based on
        reviewer trust scores.
        """
        # Get all reviews for this claim with reviewer trust scores
        result = await self.session.execute(
            select(Review, Agent)
            .join(Agent, Review.agent_id == Agent.id)
            .where(Review.claim_id == claim_id)
        )
        
        reviews = []
        total_weight = 0.0
        weighted_confidence = 0.0
        
        for review, agent in result:
            # Apply trust weight from caller's perspective
            trust = trust_weights.get(str(agent.id), agent.trust_score) if trust_weights else agent.trust_score
            
            reviews.append({
                "reviewer_id": str(agent.id),
                "reviewer_name": agent.name,
                "confidence": review.confidence,
                "assessment": review.assessment,
                "trust_weight": trust,
            })
            
            if review.confidence is not None:
                weighted_confidence += review.confidence * trust
                total_weight += trust
        
        aggregated = weighted_confidence / total_weight if total_weight > 0 else None
        
        return {
            "claim_id": str(claim_id),
            "aggregated_confidence": aggregated,
            "review_count": len(reviews),
            "reviews": reviews,
        }
    
    async def propagate_through_evidence(
        self,
        claim_id: UUID,
    ) -> dict:
        """
        Compute confidence by combining direct reviews with
        confidence propagated from supporting evidence.
        
        This is an experimental feature — the exact propagation
        algorithm is TBD based on domain expert feedback.
        """
        # Direct confidence
        direct = await self.compute_confidence(claim_id)
        
        # Evidence chain confidence
        from phiacta.services.traversal_service import TraversalService
        traversal = TraversalService(self.session)
        evidence = await traversal.get_evidence_chain(claim_id)
        
        evidence_confidences = []
        for node in evidence["nodes"]:
            if node["id"] != str(claim_id):
                ec = await self.compute_confidence(UUID(node["id"]))
                if ec["aggregated_confidence"] is not None:
                    evidence_confidences.append(ec["aggregated_confidence"])
        
        # Simple propagation: average of evidence confidences
        propagated = sum(evidence_confidences) / len(evidence_confidences) if evidence_confidences else None
        
        return {
            "claim_id": str(claim_id),
            "direct_confidence": direct["aggregated_confidence"],
            "propagated_confidence": propagated,
            "combined_confidence": self._combine(direct["aggregated_confidence"], propagated),
            "evidence_count": len(evidence_confidences),
        }
    
    def _combine(self, direct: float | None, propagated: float | None) -> float | None:
        if direct is None and propagated is None:
            return None
        if direct is None:
            return propagated
        if propagated is None:
            return direct
        # Weight direct evidence more heavily
        return 0.7 * direct + 0.3 * propagated
```

### 3.4 Query API Endpoints

`src/phiacta/api/v1/query.py`:

```python
from uuid import UUID
from fastapi import APIRouter
from pydantic import BaseModel, Field
from phiacta.api.deps import DBSession, CurrentAgent
from phiacta.services.search_service import SearchService
from phiacta.services.traversal_service import TraversalService
from phiacta.services.confidence_service import ConfidenceService

router = APIRouter(prefix="/query", tags=["query"])

class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=20, le=100)
    claim_types: list[str] | None = None
    namespace_id: UUID | None = None

class TraverseRequest(BaseModel):
    start_id: UUID
    depth: int = Field(default=2, le=10)
    edge_types: list[str] | None = None
    direction: str = "both"

@router.post("/search")
async def search(request: SearchRequest, db: DBSession, agent: CurrentAgent):
    service = SearchService(db)
    return await service.semantic_search(
        query=request.query,
        top_k=request.top_k,
        claim_types=request.claim_types,
        namespace_id=request.namespace_id,
    )

@router.post("/traverse")
async def traverse(request: TraverseRequest, db: DBSession, agent: CurrentAgent):
    service = TraversalService(db)
    return await service.traverse(
        start_id=request.start_id,
        depth=request.depth,
        edge_types=request.edge_types,
        direction=request.direction,
    )

@router.get("/confidence/{claim_id}")
async def get_confidence(claim_id: UUID, db: DBSession, agent: CurrentAgent):
    service = ConfidenceService(db)
    return await service.compute_confidence(claim_id)
```

### 3.5 Duplicate Detection

`src/phiacta/services/duplicate_service.py`:

```python
async def find_duplicates(
    session: AsyncSession,
    content: str,
    threshold: float = 0.92,
) -> list[dict]:
    """
    Find potentially duplicate claims using embedding similarity.
    Used during bundle submission to warn about near-duplicates.
    """
    embedding = await generate_embedding(content)
    
    sql = """
        SELECT 
            c.id,
            c.content,
            1 - (c.embedding <=> :embedding) as similarity
        FROM claims c
        WHERE c.embedding IS NOT NULL
            AND 1 - (c.embedding <=> :embedding) > :threshold
        ORDER BY c.embedding <=> :embedding
        LIMIT 5
    """
    
    result = await session.execute(
        text(sql),
        {"embedding": embedding, "threshold": threshold}
    )
    
    return [
        {"id": str(row.id), "content": row.content, "similarity": row.similarity}
        for row in result
    ]
```

### Files Created in Phase 3

| File | Purpose |
|------|---------|
| `src/phiacta/services/search_service.py` | Semantic search via pgvector |
| `src/phiacta/services/traversal_service.py` | Graph traversal with CTEs |
| `src/phiacta/services/confidence_service.py` | Confidence aggregation |
| `src/phiacta/services/duplicate_service.py` | Duplicate detection |
| `src/phiacta/api/v1/query.py` | Query endpoints |
| `tests/integration/test_search_api.py` | Search tests |
| `tests/integration/test_traversal_api.py` | Traversal tests |

### Success Criteria

- [ ] `POST /v1/query/search` returns semantically similar claims
- [ ] `POST /v1/query/traverse` returns a graph of related claims
- [ ] Cycle detection prevents infinite traversal loops
- [ ] Confidence aggregation weights by reviewer trust
- [ ] Duplicate detection warns on high-similarity submissions
- [ ] Search returns results in <500ms for 10K claims

### Risk: IVFFlat index recall at scale

**Mitigation:** Start without the vector index for <10K claims. Add IVFFlat with `lists = sqrt(n)` after 10K. Monitor recall metrics. Consider HNSW at 1M+ claims.

### Risk: Recursive CTE performance with deep graphs

**Mitigation:** Enforce `MAX_TRAVERSAL_DEPTH` (default 10). Add query timeout. Consider materializing common traversal patterns as views.

---

## Phase 4: Extension System (2-3 days)

### Objective

Implement the extension base classes, SDK client, plugin discovery, and a working paper ingestion extension that proves the system works end-to-end.

### 4.1 Extension Base Classes

`src/phiacta/extensions/base.py`:

As specified in `extension-protocol.md`, implement:
- `Source`, `ExtractedClaim`, `ExtractedEdge`, `ExtractedArtifact`, `ExtractionResult`
- `QueryRequest`, `QueryResponse`
- `InputExtension` ABC with `ingest()` and `validate()`
- `OutputExtension` ABC with `query()`

### 4.2 SDK Client

`src/phiacta/extensions/client.py`:

```python
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

class PhiactaClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.timeout = timeout
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def submit_bundle(
        self,
        result: ExtractionResult,
        source: Source,
        idempotency_key: str,
        contributor_id: str,
    ) -> BundleResponse:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            payload = {
                "idempotency_key": idempotency_key,
                "source": source.to_dict(),
                "claims": [c.to_dict() for c in result.claims],
                "edges": [e.to_dict() for e in result.edges],
                "artifacts": [a.to_dict() for a in result.artifacts],
                "contributor_id": contributor_id,
            }
            response = await client.post(
                f"{self.base_url}/v1/bundles",
                json=payload,
                headers=self.headers,
            )
            response.raise_for_status()
            return BundleResponse(**response.json())
    
    async def search(self, query: str, top_k: int = 20, **filters) -> list[dict]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/v1/query/search",
                json={"query": query, "top_k": top_k, **filters},
                headers=self.headers,
            )
            response.raise_for_status()
            return response.json()
```

### 4.3 Extension Registry

`src/phiacta/extensions/registry.py`:

```python
from datetime import datetime
from typing import Any
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from phiacta.models.agent import Agent

class ExtensionRegistry:
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def register(self, manifest: dict) -> dict:
        """Register a new extension and provision API credentials."""
        from phiacta.services.auth_service import generate_api_key
        
        raw_key, hashed_key = generate_api_key(manifest["extension_id"])
        
        agent = Agent(
            agent_type="extension",
            name=manifest["extension_id"],
            attrs={
                "manifest": manifest,
                "registered_at": datetime.utcnow().isoformat(),
            },
            api_key_hash=hashed_key,
        )
        self.session.add(agent)
        await self.session.commit()
        
        return {
            "extension_id": manifest["extension_id"],
            "api_key": raw_key,  # Shown only once
            "status": "active",
            "registered_at": agent.attrs["registered_at"],
        }
    
    async def list_extensions(
        self,
        extension_type: str | None = None,
        status: str = "active",
    ) -> list[dict]:
        query = select(Agent).where(Agent.agent_type == "extension")
        result = await self.session.execute(query)
        
        extensions = []
        for agent in result.scalars():
            manifest = agent.attrs.get("manifest", {})
            if extension_type and manifest.get("type") != extension_type:
                continue
            extensions.append({
                "extension_id": agent.name,
                "name": manifest.get("name"),
                "type": manifest.get("type"),
                "version": manifest.get("version"),
                "description": manifest.get("description"),
            })
        
        return extensions
```

### 4.4 Paper Ingestion Extension

This is the **critical path**. If this doesn't work well enough, pause and wait for AI to improve.

`extensions/paper_ingestion/extension.py`:

```python
import hashlib
from phiacta.extensions.base import (
    InputExtension, Source, ExtractionResult,
    ExtractedClaim, ExtractedEdge,
)
from extensions.paper_ingestion.pdf_parser import extract_text_and_sections
from extensions.paper_ingestion.claim_extractor import extract_claims_with_llm

class PaperIngestionExtension(InputExtension):
    name = "paper-ingestion"
    version = "1.0.0"
    description = "Extracts claims, evidence, and relationships from academic papers"
    
    async def ingest(self, source: Source) -> ExtractionResult:
        """
        Process a PDF paper and extract structured knowledge.
        
        Expected source.attrs:
            pdf_path (str): Path to the PDF file
            doi (str, optional): DOI of the paper
        """
        pdf_path = source.attrs.get("pdf_path")
        if not pdf_path:
            raise ValueError("pdf_path is required in source.attrs")
        
        # Parse PDF
        sections = await extract_text_and_sections(pdf_path)
        
        # Extract claims using LLM
        raw_claims = await extract_claims_with_llm(sections)
        
        # Convert to structured claims
        claims = []
        edges = []
        
        for i, rc in enumerate(raw_claims):
            claim = ExtractedClaim(
                temp_id=f"c{i}",
                content=rc["content"],
                claim_type=rc["type"],
                confidence=rc.get("extraction_confidence", 0.8),
                attrs={
                    "section": rc.get("section"),
                    "context": rc.get("context"),
                },
            )
            claims.append(claim)
            
            # Create edges for relationships identified by LLM
            if rc.get("supports"):
                edges.append(ExtractedEdge(
                    source_temp_id=f"c{i}",
                    target_temp_id=rc["supports"],
                    edge_type="supports",
                ))
        
        return ExtractionResult(claims=claims, edges=edges)
    
    async def validate(self, result: ExtractionResult) -> list[str]:
        warnings = []
        if len(result.claims) < 3:
            warnings.append(
                f"Only {len(result.claims)} claims extracted. "
                "Papers typically yield 10+ claims. Check extraction quality."
            )
        return warnings
```

`extensions/paper_ingestion/claim_extractor.py`:

```python
from openai import AsyncOpenAI
from phiacta.config import settings

client = AsyncOpenAI(api_key=settings.openai_api_key)

EXTRACTION_PROMPT = """
You are a scientific knowledge extractor. Given a section of an academic paper,
extract atomic claims that can stand alone as knowledge assertions.

For each claim, provide:
1. content: The claim statement (one sentence, self-contained)
2. type: One of "empirical" (data-backed), "methodological", "interpretive", or "hypothesis"
3. extraction_confidence: 0.0-1.0, how confident you are in the extraction accuracy
4. section: Which section this came from
5. supports: If this claim supports another claim in your list, reference it by index

Output as JSON array. Be thorough but avoid trivial claims (definitions, background).

Paper section:
{text}
"""

async def extract_claims_with_llm(sections: list[dict]) -> list[dict]:
    all_claims = []
    
    for section in sections:
        if section["type"] in ["abstract", "introduction", "results", "discussion", "conclusion"]:
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a precise scientific knowledge extractor."},
                    {"role": "user", "content": EXTRACTION_PROMPT.format(text=section["text"])},
                ],
                response_format={"type": "json_object"},
            )
            
            import json
            claims = json.loads(response.choices[0].message.content).get("claims", [])
            for claim in claims:
                claim["section"] = section["name"]
            all_claims.extend(claims)
    
    return all_claims
```

### 4.5 Extension API Endpoints

`src/phiacta/api/v1/extensions.py`:

```python
from fastapi import APIRouter, HTTPException
from phiacta.api.deps import DBSession, CurrentAgent
from phiacta.extensions.registry import ExtensionRegistry
from phiacta.schemas.extensions import ExtensionManifest

router = APIRouter(prefix="/extensions", tags=["extensions"])

@router.post("/register")
async def register_extension(
    manifest: ExtensionManifest,
    db: DBSession,
    agent: CurrentAgent,
):
    # Require admin scope for registration
    if "admin" not in agent.attrs.get("scopes", []):
        raise HTTPException(status_code=403, detail="Admin scope required")
    
    registry = ExtensionRegistry(db)
    return await registry.register(manifest.model_dump())

@router.get("")
async def list_extensions(
    db: DBSession,
    agent: CurrentAgent,
    extension_type: str | None = None,
):
    registry = ExtensionRegistry(db)
    return await registry.list_extensions(extension_type=extension_type)
```

### Files Created in Phase 4

| File | Purpose |
|------|---------|
| `src/phiacta/extensions/__init__.py` | Extension package |
| `src/phiacta/extensions/base.py` | Base classes and data types |
| `src/phiacta/extensions/client.py` | SDK HTTP client |
| `src/phiacta/extensions/registry.py` | Extension registration |
| `src/phiacta/extensions/runner.py` | Extension runner/server |
| `src/phiacta/api/v1/extensions.py` | Extension API |
| `src/phiacta/schemas/extensions.py` | Extension manifest schema |
| `extensions/__init__.py` | Built-in extensions package |
| `extensions/paper_ingestion/__init__.py` | Paper ingestion package |
| `extensions/paper_ingestion/extension.py` | Main extension class |
| `extensions/paper_ingestion/pdf_parser.py` | PDF text extraction |
| `extensions/paper_ingestion/claim_extractor.py` | LLM claim extraction |
| `extensions/paper_ingestion/citation_resolver.py` | DOI resolution |
| `extensions/paper_ingestion/manifest.json` | Extension manifest |
| `extensions/manual_entry/__init__.py` | Manual entry package |
| `extensions/manual_entry/extension.py` | Manual entry extension |
| `tests/extensions/test_paper_ingestion.py` | Paper ingestion tests |

### Success Criteria

- [ ] Paper ingestion processes a sample PDF end-to-end
- [ ] Extracted claims appear in the database with correct types
- [ ] Relationships between claims are preserved as edges
- [ ] Provenance links claims back to the source PDF
- [ ] Extension registration returns working API credentials
- [ ] `GET /v1/extensions` lists registered extensions
- [ ] SDK client successfully submits bundles

### Critical Go/No-Go Decision

After Phase 4, evaluate paper ingestion quality:

**GO criteria:**
- Extracts 10+ meaningful claims from a typical 10-page paper
- Extraction confidence correlates with actual accuracy (spot check 20 claims)
- Relationships make semantic sense (supports/contradicts are directionally correct)
- End-to-end latency <60s per paper

**NO-GO criteria:**
- <5 claims per paper on average
- >30% of claims are trivial (definitions, citations as claims)
- Relationships are random or always the same type
- Frequent LLM failures or hallucinations

If NO-GO: Pause, improve the extraction prompts, try different models, or wait for better LLMs. Do not proceed to Phase 5 with broken ingestion.

---

## Phase 5: Production Ready (2 days)

### Objective

Prepare for deployment: Docker Compose for staging, Kubernetes manifests for production, monitoring, rate limiting, and documentation.

### 5.1 Production Docker Compose

`docker-compose.prod.yml`:

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: phiacta
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER} -d phiacta"]
      interval: 10s
      timeout: 5s
      retries: 5

  backend:
    image: phiacta:${VERSION:-latest}
    environment:
      DATABASE_URL: postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@db:5432/phiacta
      OPENAI_API_KEY: ${OPENAI_API_KEY}
      ENVIRONMENT: production
      LOG_LEVEL: info
      LOG_FORMAT: json
    ports:
      - "8000:8000"
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G

volumes:
  pgdata:
```

### 5.2 Kubernetes Manifests

Create in `deploy/k8s/`:

| File | Purpose |
|------|---------|
| `namespace.yaml` | Dedicated namespace |
| `configmap.yaml` | Non-secret configuration |
| `secret.yaml` | Template for secrets |
| `deployment.yaml` | Backend deployment (3 replicas) |
| `service.yaml` | ClusterIP service |
| `ingress.yaml` | Ingress with TLS |
| `migration-job.yaml` | Pre-deploy migration job |
| `hpa.yaml` | Horizontal pod autoscaler |

As specified in `deployment.md`.

### 5.3 Rate Limiting

`src/phiacta/middleware/rate_limit.py`:

```python
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from collections import defaultdict
import time

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, default_limit: int = 60, window_seconds: int = 60):
        super().__init__(app)
        self.default_limit = default_limit
        self.window_seconds = window_seconds
        self.requests: dict[str, list[float]] = defaultdict(list)
    
    async def dispatch(self, request: Request, call_next):
        # Extract API key from header
        auth = request.headers.get("Authorization", "")
        key = auth[7:] if auth.startswith("Bearer ") else request.client.host
        
        now = time.time()
        window_start = now - self.window_seconds
        
        # Clean old requests
        self.requests[key] = [t for t in self.requests[key] if t > window_start]
        
        # Check limit
        if len(self.requests[key]) >= self.default_limit:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={
                    "X-RateLimit-Limit": str(self.default_limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(window_start + self.window_seconds)),
                }
            )
        
        # Record request
        self.requests[key].append(now)
        
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.default_limit)
        response.headers["X-RateLimit-Remaining"] = str(
            self.default_limit - len(self.requests[key])
        )
        return response
```

### 5.4 Structured Logging

`src/phiacta/logging.py`:

```python
import structlog
from phiacta.config import settings

def configure_logging():
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    
    if settings.log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(structlog, settings.log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
```

### 5.5 Request ID Middleware

```python
from uuid import uuid4
from starlette.middleware.base import BaseHTTPMiddleware
import structlog

class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = str(uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
```

### 5.6 Health Endpoint Enhancements

```python
@app.get("/ready")
async def ready(db: DBSession):
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ready", "database": "connected"}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "database": str(e)}
        )
```

### 5.7 Documentation

| File | Purpose |
|------|---------|
| `docs/api/README.md` | API overview and authentication |
| `docs/api/bundles.md` | Bundle submission guide |
| `docs/api/queries.md` | Search and traversal guide |
| `docs/extensions/quickstart.md` | 1-page extension tutorial |
| `docs/extensions/reference.md` | Full SDK reference |
| `docs/deployment/docker.md` | Docker deployment guide |
| `docs/deployment/kubernetes.md` | K8s deployment guide |

### Files Created in Phase 5

| File | Purpose |
|------|---------|
| `docker-compose.prod.yml` | Production compose file |
| `deploy/k8s/*.yaml` | Kubernetes manifests |
| `src/phiacta/middleware/__init__.py` | Middleware package |
| `src/phiacta/middleware/rate_limit.py` | Rate limiting |
| `src/phiacta/middleware/request_id.py` | Request ID injection |
| `src/phiacta/logging.py` | Structured logging config |
| `docs/api/*.md` | API documentation |
| `docs/extensions/*.md` | Extension developer docs |
| `docs/deployment/*.md` | Deployment guides |

### Success Criteria

- [ ] `docker-compose -f docker-compose.prod.yml up` runs successfully
- [ ] Kubernetes manifests apply to a cluster without errors
- [ ] Rate limiting returns 429 after exceeding limits
- [ ] All log output is structured JSON in production
- [ ] Request IDs appear in logs and response headers
- [ ] `/ready` returns 503 when database is unreachable
- [ ] Documentation covers all public API endpoints

---

## Dependency Graph

```
Phase 0 (Setup)
    │
    ▼
Phase 1 (Data Layer)
    │
    ▼
Phase 2 (API Layer)
    │
    ├─────────────────┐
    ▼                 ▼
Phase 3            Phase 4
(Knowledge Graph)  (Extensions)
    │                 │
    └────────┬────────┘
             ▼
        Phase 5
   (Production Ready)
```

Phases 3 and 4 can run in parallel once Phase 2 is complete.

---

## Risk Register

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| Paper ingestion AI doesn't work well enough | **Critical** | Medium | Build it first. Stop if it fails. Iterate on prompts. |
| pgvector performance at scale | High | Low | Start without index. Add IVFFlat at 10K claims. Monitor. |
| OpenAI rate limits during bulk ingestion | Medium | Medium | Implement batching, backoff, and client-side rate limiting |
| Recursive CTE timeout on deep graphs | Medium | Low | Enforce max depth. Add query timeout. Materialize common paths. |
| Extension API misuse / garbage data | Medium | Medium | Capability enforcement. Rate limits. Trust scoring. |
| PostgreSQL connection exhaustion | Medium | Low | Pool sizing. Monitor with pg_stat_activity. PgBouncer if needed. |
| Breaking schema changes after launch | High | Medium | Alembic discipline. Two-phase deployments. Version API. |

---

## Milestones

| Milestone | Target | Criteria |
|-----------|--------|----------|
| **M0: Dev Environment** | Day 0.5 | Docker Compose runs, CI passes |
| **M1: Data Layer** | Day 3.5 | All 11 tables, migrations work, repos tested |
| **M2: API Layer** | Day 5.5 | Bundle submission and claim retrieval work |
| **M3: Knowledge Graph** | Day 8 | Semantic search and traversal work |
| **M4: Paper Ingestion** | Day 10 | End-to-end paper → claims pipeline works |
| **M5: Production** | Day 12 | Deployable to staging/prod, docs complete |

---

## Success Metrics (v0.1)

| Metric | Target |
|--------|--------|
| Papers ingested | 100 |
| Claims extracted | 1,000+ |
| Meaningful relationships | 500+ |
| Search query latency (p95) | <500ms |
| Bundle submission latency (p95) | <5s |
| Test coverage | >80% |
| Type check | `mypy --strict` passes |

---

## Next Steps After v0.1

1. **WebSocket subscriptions** for real-time updates
2. **View rendering** (paper view, proof tree, comparison table)
3. **Voice/dictation extension** for low-friction input
4. **Blackboard photo extension** for informal capture
5. **User authentication** (JWT/OAuth) for multi-tenancy
6. **Admin dashboard** for extension management
7. **Paper export extension** for generating traditional papers from claims

---

*Last updated: 2026-02-08*
*Document version: 1.0*
