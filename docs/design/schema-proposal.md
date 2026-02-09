# Knowledge Backend: Core Schema Proposal

## Design Philosophy

The central insight driving this schema is that **a knowledge base is a labeled, versioned, attributed graph** where:

- **Nodes** are *claims* -- atomic assertions about the world.
- **Edges** are *typed relationships* between claims -- support, contradiction, dependency, refinement, etc.
- **Provenance** is first-class -- every node and edge traces back to an agent, a source, and a moment in time.
- **Claims are immutable snapshots** -- when knowledge evolves, we create new versions linked to their predecessors, preserving full history.

This is *not* a general-purpose knowledge graph (like Wikidata). It is specifically designed for **scientific and intellectual knowledge**: things that have evidence, confidence, dependencies, and that evolve through discourse. The schema encodes the *epistemology*, not just the *ontology*.

### Key Design Decisions (and why)

**Why claims, not documents?** Documents (papers, notes) are *containers* -- they bundle many claims into one artifact. But reasoning happens at the claim level: Theorem A depends on Lemma B, not on "paper X." We decompose knowledge into atomic claims and track the documents as provenance.

**Why immutable versions?** Scientific claims get cited. If claim C1 changes in place, every citation to it becomes ambiguous -- does it reference the original or the revision? Immutable versions with explicit `supersedes` links give stable reference points while still allowing evolution.

**Why typed edges instead of free-form relations?** AI reasoning over the graph requires predictable semantics. If we know that edge type `depends_on` is transitive, we can compute dependency chains. Free-form strings destroy this. But we also need extensibility, so relationship types live in a registry table -- you can add new types, but each type must declare its formal properties.

**Why PostgreSQL, not Neo4j?** The graph here is a *property graph with rich node metadata*. PostgreSQL handles this well with foreign keys and JSONB for flexible attributes. We get ACID transactions, pgvector for embeddings, and mature tooling. The graph traversal patterns we need (dependency chains, evidence aggregation) are bounded-depth and work fine with recursive CTEs. If traversal performance becomes a bottleneck later, we can add Apache AGE (a Postgres graph extension) without changing the schema.

---

## 1. Core Entities

### 1.1 Claim

The atomic unit of knowledge. A claim is a single, self-contained assertion.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Immutable primary key |
| `claim_type` | enum | `assertion`, `definition`, `theorem`, `conjecture`, `observation`, `method`, `question` |
| `content` | text | Human-readable statement of the claim |
| `formal_content` | text (nullable) | Machine-verifiable representation (Lean, logic, equation) |
| `namespace_id` | UUID (FK) | The domain/context this claim belongs to |
| `created_by` | UUID (FK -> Agent) | Who created this version |
| `created_at` | timestamptz | When this version was created |
| `version` | int | Version number within the claim lineage |
| `lineage_id` | UUID | Groups all versions of the "same" claim |
| `supersedes` | UUID (FK -> Claim, nullable) | The previous version this replaces |
| `status` | enum | `draft`, `active`, `deprecated`, `retracted` |
| `embedding` | vector(1536) | Semantic embedding for similarity search |
| `attrs` | jsonb | Extensible key-value metadata |

**Rationale:** Claims are the nodes of the knowledge graph. Everything else -- evidence, relationships, provenance -- hangs off of claims. The `claim_type` enum distinguishes the *epistemic role* of the claim (an observation is different from a theorem), which matters for reasoning. The `formal_content` field allows optional machine verification without forcing it.

The `lineage_id` + `version` + `supersedes` triple implements immutable versioning: all versions of a claim share a `lineage_id`, each has an incrementing `version`, and `supersedes` points to the specific predecessor. This allows both "give me the latest version" and "give me the exact version that was cited."

### 1.2 Edge (Relationship)

A typed, directed relationship between two claims.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `source_id` | UUID (FK -> Claim) | The origin claim |
| `target_id` | UUID (FK -> Claim) | The destination claim |
| `edge_type` | text (FK -> EdgeType) | The relationship type |
| `strength` | real (nullable) | How strongly the relationship holds (0.0 to 1.0) |
| `created_by` | UUID (FK -> Agent) | Who asserted this relationship |
| `created_at` | timestamptz | When |
| `source_id_provenance` | UUID (FK -> Source, nullable) | Where this relationship was stated |
| `attrs` | jsonb | Extensible metadata (e.g., conditions, context) |

**Rationale:** Edges are the core of the graph. They are *themselves* asserted by agents and have provenance -- the claim "A supports B" is itself a knowledge claim that someone made and that can be disputed. The `strength` field captures degree (e.g., "weakly supports" vs "strongly supports") without overcomplicating the type system.

Edges reference specific claim versions (not lineages), because the relationship "A supports B" may not hold after B is revised. This is intentional: when claims evolve, relationships should be re-evaluated.

### 1.3 EdgeType (Relationship Type Registry)

Defines the vocabulary of relationships.

| Field | Type | Description |
|-------|------|-------------|
| `name` | text (PK) | Canonical name: `supports`, `contradicts`, etc. |
| `description` | text | Human-readable definition |
| `inverse_name` | text (nullable) | The inverse relationship (e.g., `supports` <-> `supported_by`) |
| `is_transitive` | boolean | Can be chained (A->B->C implies A->C) |
| `is_symmetric` | boolean | A->B implies B->A |
| `category` | text | Grouping: `evidential`, `logical`, `structural`, `editorial` |

**Rationale:** This is the extensibility mechanism. The initial set of edge types is fixed (see Section 2), but new types can be added by inserting into this table. Declaring formal properties (`is_transitive`, `is_symmetric`) enables automated reasoning without hardcoding knowledge about each type.

### 1.4 Agent

Any entity that contributes knowledge: a human researcher, an AI model, an automated pipeline.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `agent_type` | enum | `human`, `ai`, `organization`, `pipeline` |
| `name` | text | Display name |
| `external_id` | text (nullable) | ORCID, model ID, system identifier |
| `attrs` | jsonb | Extensible metadata (affiliations, credentials) |
| `created_at` | timestamptz | When this agent was registered |

**Rationale:** We need to distinguish human from AI contributions for trust calibration. An AI-extracted claim carries different epistemic weight than a peer-reviewed human assertion. The `external_id` field links to identity systems (ORCID for researchers, model version strings for AI).

### 1.5 Source

A real-world artifact from which knowledge was extracted: a paper, a recording, a photo, a conversation.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `source_type` | enum | `paper`, `preprint`, `recording`, `photo`, `conversation`, `code`, `dataset`, `url`, `manual_entry` |
| `title` | text (nullable) | Human-readable title |
| `external_ref` | text (nullable) | DOI, URL, arXiv ID, file path |
| `content_hash` | text (nullable) | SHA-256 of the source artifact for integrity |
| `submitted_by` | UUID (FK -> Agent) | Who submitted this source |
| `submitted_at` | timestamptz | When |
| `attrs` | jsonb | Extensible metadata (authors, journal, date, etc.) |

**Rationale:** Sources are the *real-world grounding*. A claim's credibility depends partly on where it came from. The `content_hash` field provides integrity verification -- we can detect if the underlying artifact has changed since the claim was extracted.

### 1.6 Provenance (Claim-Source Link)

Links a claim to the source(s) it was derived from, with details about how.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `claim_id` | UUID (FK -> Claim) | The claim |
| `source_id` | UUID (FK -> Source) | The source it came from |
| `extracted_by` | UUID (FK -> Agent) | Who/what performed the extraction |
| `extraction_method` | text (nullable) | How: `manual`, `nlp`, `ocr`, `dictation`, `formal_derivation` |
| `location_in_source` | text (nullable) | Where in the source: page number, timestamp, coordinates |
| `extracted_at` | timestamptz | When |
| `confidence` | real (nullable) | Extraction confidence (0.0 to 1.0) |
| `attrs` | jsonb | Additional context |

**Rationale:** Provenance is a many-to-many relationship: one claim can come from multiple sources (corroboration), and one source yields many claims. The `extraction_method` and `confidence` fields capture the reliability of the extraction process itself -- an OCR'd blackboard photo has different reliability than a manually entered theorem.

### 1.7 Namespace

A domain, project, or scope that groups related claims.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `name` | text | Human-readable name |
| `parent_id` | UUID (FK -> Namespace, nullable) | For hierarchical namespaces |
| `description` | text (nullable) | What this namespace covers |
| `attrs` | jsonb | Extensible metadata |
| `created_at` | timestamptz | When |

**Rationale:** Namespaces scope the knowledge graph. "X causes Y" might be true in biology but meaningless in mathematics. Namespaces also serve as access control boundaries and organizational units. The hierarchical `parent_id` allows nesting (e.g., `physics > quantum > entanglement`).

### 1.8 Review

An explicit assessment of a claim by an agent.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `claim_id` | UUID (FK -> Claim) | The claim being reviewed |
| `reviewer_id` | UUID (FK -> Agent) | Who reviewed it |
| `verdict` | enum | `endorse`, `dispute`, `request_revision`, `retract` |
| `confidence` | real | Reviewer's confidence in this claim (0.0 to 1.0) |
| `comment` | text (nullable) | Explanation |
| `created_at` | timestamptz | When |

**Rationale:** Peer review is how science validates claims. Rather than a single global "confidence score," confidence is inherently *perspectival* -- different reviewers may have different assessments. The aggregate confidence of a claim can be computed from its reviews. This also supports the open question about "how do we handle disagreement" -- we represent it explicitly.

---

## 2. Relationship Types

The initial set of edge types, organized by category:

### Evidential
| Name | Inverse | Transitive | Symmetric | Description |
|------|---------|------------|-----------|-------------|
| `supports` | `supported_by` | No | No | Source provides evidence for target |
| `contradicts` | `contradicts` | No | Yes | Source provides evidence against target |
| `corroborates` | `corroborated_by` | No | No | Independent evidence for the same target |

### Logical
| Name | Inverse | Transitive | Symmetric | Description |
|------|---------|------------|-----------|-------------|
| `depends_on` | `depended_on_by` | Yes | No | Source requires target to hold |
| `assumes` | `assumed_by` | Yes | No | Source takes target as given without proof |
| `derives_from` | `derives` | Yes | No | Source is logically derived from target |
| `implies` | `implied_by` | Yes | No | If source holds, target must hold |
| `equivalent_to` | `equivalent_to` | Yes | Yes | Source and target are logically equivalent |

### Structural
| Name | Inverse | Transitive | Symmetric | Description |
|------|---------|------------|-----------|-------------|
| `generalizes` | `specializes` | Yes | No | Source is a more general form of target |
| `refines` | `refined_by` | No | No | Source is a more precise version of target |
| `part_of` | `has_part` | Yes | No | Source is a component of target |
| `instantiates` | `instantiated_by` | No | No | Source is a concrete instance of target pattern |

### Editorial
| Name | Inverse | Transitive | Symmetric | Description |
|------|---------|------------|-----------|-------------|
| `supersedes` | `superseded_by` | Yes | No | Source replaces target (versioning) |
| `related_to` | `related_to` | No | Yes | Weak/untyped association |
| `responds_to` | `responded_to_by` | No | No | Source is a response/reply to target |

### Extensibility

New edge types are added by inserting rows into `edge_types`. The `is_transitive` and `is_symmetric` flags ensure the query engine can reason over new types without code changes. A governance process (who can add edge types?) is out of scope for the schema itself but should be handled at the application layer.

---

## 3. Versioning Strategy

**Decision: Immutable claims with explicit `supersedes` edges.**

### How it works

1. Every claim is immutable once created. Its `id` never changes, its `content` never changes.
2. To "edit" a claim, you create a new claim with a new `id`, the same `lineage_id`, an incremented `version`, and a `supersedes` pointer to the old version.
3. The old claim's `status` is set to `deprecated` (or `retracted` if the content was wrong, not just outdated).
4. Edges pointing to the old version are NOT automatically migrated -- this is deliberate. The relationship "A supports B_v1" may not hold for B_v2. The author of the relationship should explicitly re-assert it for the new version.

### Why this approach?

- **Stable references:** Any external citation to claim `id=X` will always resolve to the exact content that was cited. This is critical for scientific integrity.
- **Explicit evolution:** The `supersedes` chain shows how understanding evolved. This is itself valuable knowledge.
- **No silent invalidation:** When a claim changes, dependent relationships are not silently broken. Instead, they remain attached to the old version, and the system can surface "this relationship references a deprecated claim" as a signal that re-evaluation is needed.

### Querying

- **Latest version of a claim:** `SELECT * FROM claims WHERE lineage_id = ? ORDER BY version DESC LIMIT 1`
- **Full version history:** `SELECT * FROM claims WHERE lineage_id = ? ORDER BY version`
- **Stale edges:** `SELECT e.* FROM edges e JOIN claims c ON e.target_id = c.id WHERE c.status = 'deprecated'` -- these are relationships that may need updating.

### Trade-off acknowledged

This creates more rows over time and requires applications to handle version resolution. But the alternative -- mutable claims with audit logs -- makes citations unreliable and hides the evolution of knowledge. For a system whose purpose is *tracking how knowledge evolves*, immutability is the right default.

---

## 4. Confidence and Verification Model

Confidence is **perspectival, multi-dimensional, and computed**.

### The Model

There is no single "confidence score" stamped on a claim. Instead, confidence arises from three sources:

1. **Extraction confidence** (in `provenance`): How reliably was this claim extracted from its source? An NLP pipeline assigns 0.85; a human manual entry is implicitly 1.0.

2. **Review confidence** (in `reviews`): Individual reviewers assign their personal confidence. A formal verifier might assign 1.0 to a machine-checked proof; a domain expert might assign 0.7 based on their judgment.

3. **Structural confidence** (computed): A claim that `depends_on` another claim with low confidence inherits that weakness. A claim `supported_by` five independent sources is stronger than one supported by a single source.

### Verification Status

The `claim.status` field captures the editorial lifecycle (`draft`, `active`, `deprecated`, `retracted`) but NOT the epistemic status. Epistemic status is derived:

| Status | Condition |
|--------|-----------|
| `unverified` | No reviews exist |
| `under_review` | Reviews exist but no consensus |
| `endorsed` | Majority of reviews are `endorse` with avg confidence > threshold |
| `disputed` | Reviews include both `endorse` and `dispute` |
| `formally_verified` | `formal_content` is non-null and has been machine-checked |
| `retracted` | `claim.status = 'retracted'` |

This is **computed at query time**, not stored. This means thresholds and aggregation logic can be tuned without schema changes.

### Why not a stored confidence score?

Because "how confident should we be in X?" depends on *who's asking* and *what they care about*. A mathematician wants formal verification. A policymaker wants expert consensus. A journalist wants any expert support. Computing confidence at query time lets each consumer apply their own trust model.

---

## 5. Schema Representation

### 5.1 Entity-Relationship Description

```
Namespace 1--* Claim : contains
Claim *--1 Agent : created_by
Claim *--* Source : via Provenance
Claim 1--* Edge : as source
Claim 1--* Edge : as target
Claim 1--* Review : assessed by
Edge *--1 EdgeType : typed as
Edge *--1 Agent : created_by
Review *--1 Agent : reviewer
Source *--1 Agent : submitted_by
Claim --? Claim : supersedes (self-referential, nullable)
Namespace --? Namespace : parent (self-referential, nullable)
```

### 5.2 SQL DDL (PostgreSQL)

```sql
-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";        -- pgvector for embeddings

-- ============================================================
-- AGENTS: humans, AI models, organizations, pipelines
-- ============================================================
CREATE TABLE agents (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_type  TEXT NOT NULL CHECK (agent_type IN ('human', 'ai', 'organization', 'pipeline')),
    name        TEXT NOT NULL,
    external_id TEXT,                    -- ORCID, model version, system ID
    attrs       JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_agents_external_id ON agents(external_id) WHERE external_id IS NOT NULL;

-- ============================================================
-- NAMESPACES: hierarchical domains/scopes for claims
-- ============================================================
CREATE TABLE namespaces (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        TEXT NOT NULL,
    parent_id   UUID REFERENCES namespaces(id),
    description TEXT,
    attrs       JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_namespaces_parent ON namespaces(parent_id);

-- ============================================================
-- SOURCES: real-world artifacts from which knowledge is extracted
-- ============================================================
CREATE TABLE sources (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_type  TEXT NOT NULL CHECK (source_type IN (
        'paper', 'preprint', 'recording', 'photo', 'conversation',
        'code', 'dataset', 'url', 'manual_entry'
    )),
    title        TEXT,
    external_ref TEXT,                   -- DOI, URL, arXiv ID
    content_hash TEXT,                   -- SHA-256 of source artifact
    submitted_by UUID NOT NULL REFERENCES agents(id),
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    attrs        JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_sources_external_ref ON sources(external_ref) WHERE external_ref IS NOT NULL;
CREATE INDEX idx_sources_content_hash ON sources(content_hash) WHERE content_hash IS NOT NULL;

-- ============================================================
-- CLAIMS: the atomic unit of knowledge
-- ============================================================
CREATE TABLE claims (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_type      TEXT NOT NULL CHECK (claim_type IN (
        'assertion', 'definition', 'theorem', 'conjecture',
        'observation', 'method', 'question'
    )),
    content         TEXT NOT NULL,           -- human-readable statement
    formal_content  TEXT,                    -- machine-verifiable (Lean, etc.)
    namespace_id    UUID NOT NULL REFERENCES namespaces(id),
    created_by      UUID NOT NULL REFERENCES agents(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Versioning
    lineage_id      UUID NOT NULL,           -- shared across all versions
    version         INT NOT NULL DEFAULT 1,
    supersedes      UUID REFERENCES claims(id),
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN (
        'draft', 'active', 'deprecated', 'retracted'
    )),
    -- Semantic search
    embedding       vector(1536),
    -- Extensible metadata
    attrs           JSONB NOT NULL DEFAULT '{}',

    UNIQUE (lineage_id, version)
);

-- Find latest version of a claim lineage
CREATE INDEX idx_claims_lineage ON claims(lineage_id, version DESC);
-- Find claims in a namespace
CREATE INDEX idx_claims_namespace ON claims(namespace_id);
-- Find claims by creator
CREATE INDEX idx_claims_created_by ON claims(created_by);
-- Semantic similarity search
CREATE INDEX idx_claims_embedding ON claims USING ivfflat (embedding vector_cosine_ops);
-- Full-text search on claim content
CREATE INDEX idx_claims_content_fts ON claims USING gin(to_tsvector('english', content));
-- Find active claims (most common query pattern)
CREATE INDEX idx_claims_active ON claims(status) WHERE status = 'active';

-- ============================================================
-- EDGE TYPES: the vocabulary of relationships
-- ============================================================
CREATE TABLE edge_types (
    name          TEXT PRIMARY KEY,
    description   TEXT NOT NULL,
    inverse_name  TEXT,                    -- e.g. supports <-> supported_by
    is_transitive BOOLEAN NOT NULL DEFAULT false,
    is_symmetric  BOOLEAN NOT NULL DEFAULT false,
    category      TEXT NOT NULL CHECK (category IN (
        'evidential', 'logical', 'structural', 'editorial'
    ))
);

-- Seed initial edge types
INSERT INTO edge_types (name, description, inverse_name, is_transitive, is_symmetric, category) VALUES
    -- Evidential
    ('supports',        'Source provides evidence for target',                    'supported_by',      false, false, 'evidential'),
    ('contradicts',     'Source provides evidence against target',                'contradicts',       false, true,  'evidential'),
    ('corroborates',    'Independent evidence for the same target',               'corroborated_by',   false, false, 'evidential'),
    -- Logical
    ('depends_on',      'Source requires target to hold',                         'depended_on_by',    true,  false, 'logical'),
    ('assumes',         'Source takes target as given without proof',             'assumed_by',        true,  false, 'logical'),
    ('derives_from',    'Source is logically derived from target',                'derives',           true,  false, 'logical'),
    ('implies',         'If source holds, target must hold',                      'implied_by',        true,  false, 'logical'),
    ('equivalent_to',   'Source and target are logically equivalent',             'equivalent_to',     true,  true,  'logical'),
    -- Structural
    ('generalizes',     'Source is a more general form of target',                'specializes',       true,  false, 'structural'),
    ('refines',         'Source is a more precise version of target',             'refined_by',        false, false, 'structural'),
    ('part_of',         'Source is a component of target',                        'has_part',          true,  false, 'structural'),
    ('instantiates',    'Source is a concrete instance of target pattern',        'instantiated_by',   false, false, 'structural'),
    -- Editorial
    ('supersedes',      'Source replaces target (versioning)',                    'superseded_by',     true,  false, 'editorial'),
    ('related_to',      'Weak/untyped association',                              'related_to',        false, true,  'editorial'),
    ('responds_to',     'Source is a response/reply to target',                  'responded_to_by',   false, false, 'editorial');

-- ============================================================
-- EDGES: typed, directed relationships between claims
-- ============================================================
CREATE TABLE edges (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id   UUID NOT NULL REFERENCES claims(id),
    target_id   UUID NOT NULL REFERENCES claims(id),
    edge_type   TEXT NOT NULL REFERENCES edge_types(name),
    strength    REAL CHECK (strength >= 0.0 AND strength <= 1.0),
    created_by  UUID NOT NULL REFERENCES agents(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_provenance UUID REFERENCES sources(id),  -- where this relationship was stated
    attrs       JSONB NOT NULL DEFAULT '{}',

    -- Prevent duplicate edges of the same type between the same claims by the same agent
    UNIQUE (source_id, target_id, edge_type, created_by)
);

CREATE INDEX idx_edges_source ON edges(source_id);
CREATE INDEX idx_edges_target ON edges(target_id);
CREATE INDEX idx_edges_type ON edges(edge_type);

-- ============================================================
-- PROVENANCE: links claims to their source artifacts
-- ============================================================
CREATE TABLE provenance (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_id            UUID NOT NULL REFERENCES claims(id),
    source_id           UUID NOT NULL REFERENCES sources(id),
    extracted_by        UUID NOT NULL REFERENCES agents(id),
    extraction_method   TEXT,            -- 'manual', 'nlp', 'ocr', 'dictation', 'formal_derivation'
    location_in_source  TEXT,            -- page number, timestamp, coordinates
    extracted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    confidence          REAL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    attrs               JSONB NOT NULL DEFAULT '{}',

    UNIQUE (claim_id, source_id, extracted_by)
);

CREATE INDEX idx_provenance_claim ON provenance(claim_id);
CREATE INDEX idx_provenance_source ON provenance(source_id);

-- ============================================================
-- REVIEWS: assessments of claims by agents
-- ============================================================
CREATE TABLE reviews (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_id    UUID NOT NULL REFERENCES claims(id),
    reviewer_id UUID NOT NULL REFERENCES agents(id),
    verdict     TEXT NOT NULL CHECK (verdict IN (
        'endorse', 'dispute', 'request_revision', 'retract'
    )),
    confidence  REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    comment     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- One review per reviewer per claim (can be updated by inserting for new version)
    UNIQUE (claim_id, reviewer_id)
);

CREATE INDEX idx_reviews_claim ON reviews(claim_id);
CREATE INDEX idx_reviews_reviewer ON reviews(reviewer_id);

-- ============================================================
-- USEFUL VIEWS
-- ============================================================

-- Latest version of each claim lineage
CREATE VIEW claims_latest AS
SELECT DISTINCT ON (lineage_id) *
FROM claims
WHERE status IN ('active', 'draft')
ORDER BY lineage_id, version DESC;

-- Claims with aggregated review stats
CREATE VIEW claims_with_confidence AS
SELECT
    c.id,
    c.lineage_id,
    c.content,
    c.claim_type,
    c.status,
    c.version,
    COUNT(r.id) AS review_count,
    AVG(r.confidence) FILTER (WHERE r.verdict = 'endorse') AS avg_endorsement_confidence,
    COUNT(*) FILTER (WHERE r.verdict = 'endorse') AS endorsement_count,
    COUNT(*) FILTER (WHERE r.verdict = 'dispute') AS dispute_count,
    CASE
        WHEN COUNT(r.id) = 0 THEN 'unverified'
        WHEN COUNT(*) FILTER (WHERE r.verdict = 'dispute') > 0
             AND COUNT(*) FILTER (WHERE r.verdict = 'endorse') > 0 THEN 'disputed'
        WHEN c.formal_content IS NOT NULL
             AND COUNT(*) FILTER (WHERE r.verdict = 'endorse') > 0 THEN 'formally_verified'
        WHEN AVG(r.confidence) FILTER (WHERE r.verdict = 'endorse') > 0.7
             AND COUNT(*) FILTER (WHERE r.verdict = 'endorse') > COUNT(*) FILTER (WHERE r.verdict = 'dispute')
             THEN 'endorsed'
        ELSE 'under_review'
    END AS epistemic_status
FROM claims c
LEFT JOIN reviews r ON r.claim_id = c.id
GROUP BY c.id;

-- Stale edges: edges pointing to deprecated/retracted claims
CREATE VIEW stale_edges AS
SELECT e.*, c.status AS target_status, c.lineage_id AS target_lineage_id
FROM edges e
JOIN claims c ON e.target_id = c.id
WHERE c.status IN ('deprecated', 'retracted');
```

---

## 6. Example Use Cases

### 6a. Researcher dictates: "I found that X improves Y by 30% in condition Z"

```
1. Input extension (dictation) receives audio, transcribes it.

2. AI pipeline (Agent: type=ai, name="dictation-pipeline-v1") creates:
   - Source: { source_type: 'recording', external_ref: 's3://recordings/2026-02-08-walk.m4a',
               content_hash: 'abc123...' }

3. NLP extraction creates:
   - Claim: { claim_type: 'observation',
              content: 'X improves Y by 30% in condition Z',
              namespace_id: <researcher's project namespace>,
              created_by: <researcher's agent id>,
              lineage_id: <new uuid>, version: 1, status: 'draft' }

4. Provenance link:
   - Provenance: { claim_id: <claim>, source_id: <recording>,
                   extracted_by: <ai pipeline agent>,
                   extraction_method: 'dictation',
                   location_in_source: '00:03:42',
                   confidence: 0.92 }

5. The claim starts as 'draft'. The researcher reviews and either:
   - Confirms it (status -> 'active')
   - Edits it (creates a new version that supersedes the draft)
```

### 6b. Paper claims Theorem A, which depends on Lemma B from another paper

```
1. Paper ingestion extension processes Paper P1:
   - Source: { source_type: 'paper', external_ref: 'doi:10.1234/p1', title: 'On Theorem A' }

2. Extracts Theorem A:
   - Claim: { claim_type: 'theorem', content: 'Theorem A: ...',
              formal_content: '-- Lean 4 proof sketch (if available)',
              namespace_id: <math/algebra> }
   - Provenance: { source_id: <paper P1>, location_in_source: 'Theorem 3.1, p.12' }

3. Paper P2 contains Lemma B:
   - Source: { source_type: 'paper', external_ref: 'doi:10.5678/p2' }
   - Claim: { claim_type: 'theorem', content: 'Lemma B: ...' }
   - Provenance: { source_id: <paper P2>, location_in_source: 'Lemma 2.3, p.7' }

4. Dependency edge:
   - Edge: { source_id: <Theorem A>, target_id: <Lemma B>,
             edge_type: 'depends_on', source_provenance: <paper P1>,
             created_by: <extraction pipeline> }

5. Now queries like "what does Theorem A depend on?" and
   "what breaks if Lemma B is retracted?" are trivial graph traversals.
```

### 6c. Two papers make contradictory claims

```
1. Paper P1 claims: "Drug X reduces symptom S in population P"
   - Claim C1: { claim_type: 'assertion', content: '...' }
   - Provenance: { source_id: <P1> }

2. Paper P2 claims: "Drug X has no effect on symptom S in population P"
   - Claim C2: { claim_type: 'assertion', content: '...' }
   - Provenance: { source_id: <P2> }

3. Contradiction edge (can be created manually or detected by AI):
   - Edge: { source_id: C1, target_id: C2, edge_type: 'contradicts',
             created_by: <whoever noticed the contradiction> }

4. Both claims exist in the graph with their evidence. The epistemic_status
   view will show both as 'disputed' once reviews exist on both sides.

5. A query "what do we know about Drug X and Symptom S?" returns both claims,
   the contradiction edge, and each claim's supporting evidence -- letting the
   consumer assess the situation rather than hiding the disagreement.
```

### 6d. Blackboard proof photo formalized into logical steps

```
1. Source created from photo:
   - Source: { source_type: 'photo', content_hash: <sha256 of image>,
               external_ref: 's3://photos/blackboard-2026-02-08.jpg' }

2. OCR + AI pipeline extracts proof structure, creating a chain of claims:
   - Claim L1: { claim_type: 'assertion', content: 'Let f be continuous on [a,b]...' }
   - Claim L2: { claim_type: 'assertion', content: 'By the mean value theorem...' }
   - Claim L3: { claim_type: 'theorem', content: 'Therefore, the integral equals...' }

3. Dependency chain via edges:
   - Edge: { source: L2, target: L1, edge_type: 'derives_from' }
   - Edge: { source: L3, target: L2, edge_type: 'derives_from' }
   - Edge: { source: L2, target: <MVT claim>, edge_type: 'depends_on' }
     (where MVT is an existing claim in the knowledge base for the Mean Value Theorem)

4. All three claims have provenance linking back to the photo source,
   with extraction_method: 'ocr', and the confidence reflecting OCR quality.

5. A formal verifier can later add formal_content (Lean proofs) to each step
   and submit reviews with verdict: 'endorse', confidence: 1.0.
```

### 6e. AI agent queries "what do we know about X?"

```sql
-- Step 1: Find claims semantically related to X using vector similarity
SELECT id, content, claim_type, status
FROM claims
WHERE status = 'active'
ORDER BY embedding <=> (SELECT embedding FROM encode('X'))  -- pgvector similarity
LIMIT 20;

-- Step 2: For each matching claim, get its evidence graph
SELECT
    c.content AS claim,
    e.edge_type,
    c2.content AS related_claim,
    cwc.epistemic_status,
    cwc.review_count,
    cwc.avg_endorsement_confidence
FROM claims c
JOIN edges e ON e.source_id = c.id OR e.target_id = c.id
JOIN claims c2 ON c2.id = CASE WHEN e.source_id = c.id THEN e.target_id ELSE e.source_id END
JOIN claims_with_confidence cwc ON cwc.id = c.id
WHERE c.id IN (<matched claim ids>);

-- Step 3: Get provenance for top claims
SELECT c.content, s.source_type, s.title, s.external_ref,
       p.extraction_method, p.confidence
FROM provenance p
JOIN claims c ON c.id = p.claim_id
JOIN sources s ON s.id = p.source_id
WHERE p.claim_id IN (<matched claim ids>);
```

The AI agent receives structured data: claims with their types, evidence relationships, epistemic status, and source provenance -- far richer than searching through paper PDFs.

---

## 7. Known Limitations and Tradeoffs

### What the schema handles well
- Atomic knowledge claims with typed relationships
- Full provenance chain from source artifact to structured claim
- Multi-perspective confidence (no forced consensus)
- Knowledge evolution with stable references
- Semantic search via embeddings
- Extensible relationship vocabulary

### Hard tradeoffs made

**1. Immutability creates data growth.** Every "edit" creates a new row. For a heavily-revised claim, the lineage could grow large. Mitigation: this is a feature, not a bug -- for knowledge tracking, you *want* the history. For storage concerns, old deprecated versions can be archived.

**2. Edges point to specific versions, not lineages.** This means when a claim is revised, existing edges become "stale" rather than automatically migrating. This is the *correct* semantic choice (the relationship may not hold for the new version), but it creates maintenance burden. The `stale_edges` view helps surface these. An application-layer tool should prompt users to re-evaluate stale edges.

**3. No native support for compound claims.** "A and B together imply C" requires representing the conjunction. Currently this would be modeled as two separate edges (C `depends_on` A, C `depends_on` B), which loses the "together" semantics. A future extension could add hyperedges (edges connecting sets of claims), but this significantly complicates the schema.

**4. Confidence aggregation is deferred to query time.** This is the right choice for flexibility, but it means there's no pre-computed "trust score" to sort by. For large-scale deployments, materialized views or caching would be needed.

**5. No built-in access control.** The schema stores knowledge, not permissions. Who can read/write which namespaces is an application-layer concern. Namespaces provide the natural boundary for access control, but the actual permission model is not defined here.

**6. Formal verification is a flag, not a system.** The `formal_content` field stores Lean/Metamath code, but the schema doesn't orchestrate verification. A separate service would need to: (a) attempt to verify `formal_content`, (b) submit a review with verdict `endorse` and confidence 1.0 on success. This is by design -- verification is a *consumer* of the schema, not part of it.

**7. Granularity is a judgment call.** What counts as an "atomic" claim? "E=mc^2" is one claim. "Under conditions C1, C2, C3, system S exhibits behavior B with probability P" might be one claim or five. The schema doesn't enforce granularity -- it relies on the extraction process and human judgment. Over-splitting loses context; under-splitting loses structure. This is a fundamental epistemological problem, not a schema problem.

**8. No native temporal/spatial reasoning.** The schema captures *when claims were made* but not *what claims are about temporally*. "X was true in the 1990s but not after 2010" would need to be encoded in the claim content or attrs, not as a first-class schema feature.

### Future Directions (not in this proposal)

- **Hyperedges** for compound relationships (A + B -> C)
- **Claim templates** for recurring structures (experimental results with standard fields)
- **Federation protocol** for cross-instance knowledge sharing
- **Annotation layer** for inline notes on claims without creating full reviews
- **Access control model** using namespaces as permission boundaries
- **Materialized confidence scores** with configurable aggregation strategies
