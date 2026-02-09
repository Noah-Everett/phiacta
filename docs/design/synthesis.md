# Knowledge Backend: Design Synthesis

*Consolidation of findings from Schema Architect, Devil's Advocate, Extension Designer, and Prior Art Researcher. 2026-02-08.*

---

## Executive Summary

The team converged on a **claim-centric, typed-relationship knowledge graph** backed by PostgreSQL + pgvector. The design borrows nanopublications' three-layer model (assertion / provenance / metadata), Wikidata's qualifier and rank patterns, Lean's explicit dependency DAGs, and Roam's block-as-atom philosophy — while avoiding their respective failure modes (RDF hostility, paper-centrism, manual structuring friction).

**The three hardest problems are not schema problems:**
1. AI-powered claim extraction from papers (if this doesn't work, the database stays empty)
2. Granularity consistency (what counts as an "atomic" claim?)
3. Adoption incentives (why would researchers use this?)

The schema is solid. The risk is everything around it.

---

## 1. Schema: What the Team Agrees On

### Core Entities (8 tables)

| Entity | Purpose | Key Insight |
|--------|---------|-------------|
| **Claim** | Atomic knowledge assertion | Immutable versions with `lineage_id` for stable references |
| **Edge** | Typed relationship between claims | Edges are themselves asserted by agents — disputable |
| **EdgeType** | Registry of relationship types | Extensible vocabulary with formal properties (`transitive`, `symmetric`) |
| **Agent** | Human, AI, org, or pipeline | Distinguishes AI-extracted from human-asserted for trust calibration |
| **Source** | Real-world artifact (paper, recording, photo) | `content_hash` for integrity verification |
| **Provenance** | Links claims to sources | Many-to-many: one claim from many sources, one source yields many claims |
| **Namespace** | Hierarchical domain scoping | "X causes Y" in biology ≠ "X causes Y" in mathematics |
| **Review** | Agent assessment of a claim | Confidence is perspectival, not global — computed from reviews at query time |

### Key Design Decisions

| Decision | Chosen Approach | Rationale |
|----------|----------------|-----------|
| Versioning | Immutable claims + `supersedes` edges | Stable citations; explicit evolution history |
| Confidence | Perspectival (per-reviewer), computed at query time | No false precision; different consumers apply different trust models |
| Database | PostgreSQL + pgvector | ACID transactions, JSONB flexibility, vector search, mature tooling |
| Relationships | Typed edges with formal properties | AI reasoning requires predictable semantics |
| Extensibility | `attrs` JSONB on every entity + extensible EdgeType registry | Domain-specific without schema changes |

### Relationship Types (15 initial, extensible)

Four categories: **Evidential** (supports, contradicts, corroborates), **Logical** (depends_on, assumes, derives_from, implies, equivalent_to), **Structural** (generalizes, refines, part_of, instantiates), **Editorial** (supersedes, related_to, responds_to).

Full SQL DDL with indexes: [schema-proposal.md](schema-proposal.md)

---

## 2. Where the Team Disagrees / Open Questions

### 2a. Evidence as a Separate Entity vs. Just Claims

**Schema Architect:** Evidence is modeled implicitly — a claim can support another claim via a `supports` edge. There is no separate Evidence table.

**Extension Designer:** The API design includes explicit `evidence` objects in bundles with their own types (`clinical_trial`, `in_vitro_experiment`, `dose_response_study`) and structured metadata.

**Resolution needed:** Are evidence nodes just claims with a different `claim_type`, or do they deserve a separate table? The schema architect's approach is more general (everything is a claim). The extension designer's approach reflects how researchers think (evidence is qualitatively different from assertions).

**Recommendation:** Use the schema architect's unified model (evidence = claims with specific claim_types) but add the extension designer's richer `claim_type` vocabulary. This avoids a separate table while preserving semantic distinction. Evidence-specific metadata lives in `attrs` JSONB.

### 2b. Artifact Storage

**Schema Architect:** No Artifact entity. Sources cover provenance; binary data is external.

**Extension Designer:** Artifacts (figures, tables, photos, audio) are a required entity linked to claims and evidence.

**Resolution needed:** Add an Artifact table. The extension use cases (blackboard photos, paper figures, dose-response tables with structured data) clearly need it. This is a gap in the current schema.

### 2c. `content_latex` as a First-Class Field

**Extension Designer:** Mathematical claims need `content_latex` as a direct field, not buried in `attrs`.

**Schema Architect:** Uses `formal_content` (for Lean/logic code) but no dedicated LaTeX field.

**Recommendation:** Keep `formal_content` for machine-verifiable representations. Add `content_latex` OR store it in `attrs` with a convention that verification extensions look for `attrs.content_latex`. The latter is more extensible (what about MathML? ASCIIMath?) but less discoverable.

### 2d. Pending References (Cross-Bundle Dependencies)

**Extension Designer:** Bundles need `pending_ref` for claims that reference not-yet-ingested entities (e.g., a paper citing another paper that hasn't been ingested yet).

**Schema Architect:** No mechanism for this.

**Recommendation:** Add a `pending_references` table that stores (source_id, external_ref, resolution_status). Resolve automatically when matching entities appear. This is critical for paper ingestion at scale.

---

## 3. Critical Challenges (Devil's Advocate)

### Dealbreakers

**1. The Authoring Problem.** No researcher will manually decompose their work into structured claims. The system lives or dies on AI-powered input extensions. If paper ingestion AI can't reliably extract claims + relationships, the knowledge base stays empty.

*Mitigation:* Build the paper ingestion extension FIRST. If it doesn't work well enough, stop and wait for AI to improve. Don't build infrastructure for an empty database.

**2. The Incentive Problem (long-term).** Researchers write papers for tenure. Contributing structured knowledge counts toward nothing.

*Mitigation for v1:* Parasitic adoption — ingest existing papers without asking researchers to change behavior. Provide value as a query/discovery tool. Only pursue active contribution after demonstrating value.

### Major Challenges

**3. Granularity consistency.** "E = mc²" and "Patient 47 showed improvement on day 12" are both "claims" but at wildly different abstraction levels. Without consistent granularity, queries return incoherent mixtures.

*Mitigation:* Lazy decomposition. Store coarse-grained claims initially; allow progressive decomposition over time. Define granularity guidelines per domain. Build AI tools that suggest decomposition.

**4. Confidence is socially constructed.** A single confidence number projects false precision. The same claim has different confidence for different people at different times.

*Mitigation:* Already addressed by the schema — confidence is per-reviewer, computed at query time. But the devil's advocate correctly notes this is more complex to implement and explain than a simple score.

**5. Versioning cascades.** When Claim B is updated, all claims depending on B may need re-evaluation. One retracted paper could cascade through thousands of downstream claims.

*Mitigation:* Distinguish hard vs. soft dependencies. Only cascade invalidation through hard dependencies. Flag (don't automatically invalidate) soft dependencies.

**6. Adversarial inputs.** Open contribution without filtering invites garbage.

*Mitigation:* Agent-based trust. New agents start with low trust. Community verification modulates effective confidence. Same unsolved problem as Wikipedia/Stack Overflow.

### Acceptable Tradeoffs

- **Tacit/procedural knowledge** doesn't fit the claim-evidence model. Out of scope for v1.
- **Scale concerns** (1B+ claims) are premature. PostgreSQL handles the first 10M easily.
- **No compound claims** (A + B → C). Model as separate edges for now; hyperedges are a v2 feature.

---

## 4. Prior Art: What to Steal, What to Avoid

### Steal

| From | What | Why |
|------|------|-----|
| Nanopublications | Three-layer model (assertion / provenance / metadata) | Cleanly separates what, how, and who |
| Wikidata | Statement-level references + rank system | Right granularity for provenance; graceful deprecation |
| Wikidata | `somevalue` / `novalue` | Explicitly represent uncertainty and absence |
| Lean/Mathlib | Explicit dependency DAGs | Composable, auditable knowledge |
| Lean/Mathlib | `sorry` pattern (unverified marker) | Claims can exist before proof; state is visible |
| Roam | Block-as-atom | Single assertions, not documents, are the unit |
| ORKG | Comparison tables | Highest-value output for researchers |
| Semantic Scholar | Field-selectable API | Clients request only what they need |
| Semantic Scholar | AI-augmented metadata (embeddings, TLDRs) | Add semantic value on top of raw data |
| RO-Crate | JSON-LD + Schema.org base | Human-readable, extensible, interoperable |

### Avoid

| From | What | Why |
|------|------|-----|
| Semantic Web / RDF | Complex syntax as input format | Hostile to humans; killed adoption |
| Semantic Web | Requiring ontology alignment upfront | Bottleneck; never works across communities |
| ORKG | Manual structuring as primary input | Does not scale; low adoption proves this |
| DBpedia | Uncritical automated extraction | Garbage in, garbage out |
| Google KG | Proprietary, closed system | Antithetical to open science |
| Neo4j (premature) | Graph database before it's needed | Operational complexity not justified at start |

---

## 5. Extension Protocol: Key Points

### Architecture

- **REST API with structured query payloads** (not GraphQL or SPARQL)
- **Bundles** as the atomic write unit (claims + evidence + relationships, accepted or rejected atomically)
- **Three query modes:** direct lookup, graph traversal, semantic search
- **Event-driven composition** for loose coupling between extensions
- **Record contradictions, don't resolve them** — the backend is a faithful record, not an arbiter

### API Surface (6 core endpoints)

| Endpoint | Purpose |
|----------|---------|
| `POST /v1/bundles` | Submit a knowledge bundle (atomic batch of claims + relationships) |
| `GET /v1/claims/{id}` | Retrieve a specific claim |
| `POST /v1/query/search` | Semantic search over claims |
| `POST /v1/query/traverse` | Graph traversal from a starting claim |
| `POST /v1/query/view` | Request a pre-defined view (paper, proof tree, comparison) |
| `WS /v1/subscribe` | Real-time event subscriptions |

### Dual Confidence Model

The extension designer surfaced a critical distinction the schema must preserve:

- **Extraction confidence** (in provenance): "How confident is the extension that it correctly extracted this claim from the source?" (e.g., OCR confidence = 0.88)
- **Claim confidence** (on claim): "How confident should we be that this claim is true?" (e.g., peer-reviewed RCT = high)

These are independent axes. A claim can be perfectly extracted (high extraction confidence) but wrong (low claim confidence), or vice versa.

Full API spec with JSON payloads: [extension-design.md](extension-design.md)

---

## 6. Implementation Priority

Based on the devil's advocate's analysis, the critical path is:

```
1. Schema + Database       → Get the foundation right (this proposal)
2. Paper Ingestion Ext.    → If this fails, nothing else matters
3. Search/Query Ext.       → Demonstrate value to researchers
4. Voice/Dictation Ext.    → Low-friction input
5. Blackboard Photo Ext.   → Showcase capability
```

**Build paper ingestion first.** It's the only way to populate the database without requiring researcher behavior change. If the AI can reliably extract claims, evidence, and relationships from PDFs, the system has a future. If not, improve the AI before building more infrastructure.

---

## 7. Schema Additions Needed (from cross-team review)

Items identified by cross-referencing all four documents that are missing from the current schema:

1. **Artifact table** — for figures, tables, photos, audio linked to claims (Extension Designer)
2. **Pending references** — for cross-bundle resolution of not-yet-ingested entities (Extension Designer)
3. **Bundle table** — to track atomic submissions as a unit (Extension Designer)
4. **Hard vs. soft dependency distinction** on edges — for cascade control (Devil's Advocate)
5. **GIN index on `attrs` JSONB** — for querying structured metadata like `p_value < 0.05` (Extension Designer)
6. **`content_latex`** field or convention — for mathematical claims (Extension Designer)
7. **Event log / changelog** — for event-driven extension composition (Extension Designer)

---

## 8. What Success Looks Like (Refined)

### v0.1 (Prove the concept)
- Schema deployed in PostgreSQL
- Paper ingestion extension processes 100 papers into structured claims
- Search extension returns structured results for natural language queries
- Manual inspection shows claims are meaningful and relationships are correct

### v0.5 (Useful tool)
- 10,000+ papers ingested
- Researchers can query "what is known about X?" and get structured, sourced answers
- Comparison views show claims side-by-side across papers
- Voice dictation extension captures informal findings

### v1.0 (Adoption)
- Researchers actively use the query interface for literature review
- Some forward-thinking researchers contribute directly via voice/dictation
- AI-generated claim graphs are reviewed and corrected by domain experts
- Paper export extension generates traditional papers from structured claims

---

## Files in This Deliverable

| File | Author | Contents |
|------|--------|----------|
| [schema-proposal.md](schema-proposal.md) | Schema Architect | Core entities, SQL DDL, versioning strategy, use cases |
| [devils-advocate.md](devils-advocate.md) | Devil's Advocate | 9 challenges, failure modes, the 3 hardest problems |
| [extension-design.md](extension-design.md) | Extension Designer | Protocol design, 4 extension deep dives, full API spec |
| [prior-art.md](prior-art.md) | Prior Art Researcher | 8 systems analyzed, synthesis of lessons |
| [synthesis.md](synthesis.md) | Coordinator | This document — cross-team synthesis and recommendations |
