# NewPublishing - Implementation Context

## Project Vision
Replace academic papers with a queryable knowledge backend. One canonical database storing semantic knowledge (claims, proofs, evidence, relationships). All interfaces are extensions.

## Design Docs
Read `docs/design/synthesis.md` first — it summarizes the schema and key decisions.

## Implementation Principles

### 1. PLAN BEFORE CODE
This project needs to be widely adopted. Poor early decisions will haunt us forever. Spend significant time on:
- Architecture decisions (language, framework, structure)
- Extension interface design (must be simple for third-party devs)
- Deployment strategy (containerization, ease of self-hosting)
- API design (versioned, stable, well-documented)

### 2. Extensibility is Everything
The core value is the schema + extension protocol. Third parties MUST be able to:
- Write new input extensions (new ways to add knowledge)
- Write new output extensions (new ways to query/view)
- Deploy their own instance easily
- Contribute extensions back to the ecosystem

**Base classes for extensions are critical.** Make it trivially easy to:
```python
class MyInputExtension(InputExtension):
    def ingest(self, source: Source) -> List[Claim]:
        ...

class MyOutputExtension(OutputExtension):  
    def query(self, request: QueryRequest) -> QueryResponse:
        ...
```

### 3. Containerization
- Docker Compose for local dev (postgres + backend + example extensions)
- Helm charts or similar for production Kubernetes
- Single-command startup: `docker compose up`
- Environment-based config, no hardcoded paths

### 4. License: GPL-3.0 (Copyleft)
You can copy, modify, and distribute freely — but if you distribute modifications, you must share your changes under the same license. This keeps the ecosystem open.

## Technical Decisions Needed

### Language
Options: Python (fast dev, AI ecosystem), Rust (performance, safety), Go (simplicity, deployment), TypeScript (full-stack).

**Recommendation:** Python backend (FastAPI) for v1. AI/ML ecosystem is Python. Rewrite hot paths in Rust later if needed.

### Database
Decision made: PostgreSQL + pgvector (see schema-proposal.md for DDL).

### Structure
```
newpublishing/
├── core/                 # Schema, models, base classes
│   ├── models/          # SQLAlchemy/Pydantic models
│   ├── extensions/      # Base classes for extensions
│   └── api/             # FastAPI routes
├── extensions/          # Built-in extensions
│   ├── input/
│   │   ├── paper_ingestion/
│   │   ├── voice_transcription/
│   │   └── manual_entry/
│   └── output/
│       ├── search/
│       ├── paper_view/
│       └── graph_viz/
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── docs/
└── tests/
```

## What Success Looks Like
1. `docker compose up` starts everything
2. Developer reads 1-page extension guide, writes a working extension in <1 hour
3. Researcher can ingest a paper, query claims, export to paper format
4. Self-hosting is trivial (single docker-compose.yml)

## Current Status
- Schema design: COMPLETE (see docs/design/)
- Implementation: NOT STARTED
- Next step: Architecture/planning phase
