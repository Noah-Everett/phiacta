# Knowledge Backend - Claude Code Context

## Project Overview
**Vision:** Replace academic papers as the medium for sharing scientific knowledge. Papers are an outdated format now that AI can synthesize, query, and reason over structured knowledge.

**Core Idea:** One canonical backend database that stores semantic knowledge (claims, proofs, evidence, relationships, dependencies). All interfaces are just extensions/views.

## Design Principles

### 1. Schema-First, Future-Proof
The backend schema is THE critical decision. It must be:
- **Maximally general** — can represent any type of knowledge
- **Semantically rich** — captures relationships, not just text
- **Machine-readable** — AI can reason over the graph
- **Human-writable** — researchers can contribute naturally
- **Extensible** — new knowledge types don't require schema changes

### 2. Extensions as First-Class Citizens
Users NEVER interact with the backend directly. All interaction is through extensions:
- **Input extensions:** How knowledge enters the system
  - Voice/dictation → structured entries
  - Photo of blackboard → formalized proof
  - PDF paper → extracted claims with citations
  - Conversation → synthesized insights
  - Code → documented algorithms
  
- **Output extensions:** How knowledge is consumed
  - Traditional paper view (for journals)
  - Interactive exploration (for learning)
  - API queries (for AI agents)
  - Citation graphs (for discovery)
  - Proof verification (for rigor)

### 3. Knowledge Graph Properties
- **Claims** are first-class entities (not paragraphs)
- **Evidence** links to claims with typed relationships
- **Provenance** tracks where every piece came from
- **Confidence** and verification status explicit
- **Dependencies** form a DAG (what assumes what)
- **Versioning** — knowledge evolves, history preserved

## What We're Building
1. **The Schema** — the core data model (this is 80% of the work)
2. **Reference Backend** — probably PostgreSQL + vector embeddings
3. **Extension Protocol** — how extensions read/write
4. **2-3 Demo Extensions** — to prove the concept
   - Paper ingestion
   - Voice/dictation input
   - Search/query interface

## Technical Considerations
- Graph database vs relational? (Neo4j vs Postgres with ltree/graph extensions)
- Vector embeddings for semantic search (pgvector)
- Proof verification integration (Lean? Metamath?)
- Multi-modal inputs (images, equations, code)
- Distributed knowledge? (multiple backends, federation?)

## What Success Looks Like
A researcher can:
1. Dictate findings while walking
2. Photo their blackboard proof
3. Have AI synthesize and verify
4. Query related work semantically
5. Export to paper format when needed
6. Other researchers can query their claims programmatically

## Open Questions
- What's the minimal viable schema?
- How do we handle uncertainty and disagreement?
- Peer review integration?
- Incentive structure for contribution?
- Intellectual property / attribution?
