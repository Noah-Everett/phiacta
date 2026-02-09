# Extension Protocol Design

## Table of Contents
1. [Extension Protocol](#1-extension-protocol)
2. [Input Extension Deep Dives](#2-input-extension-deep-dives)
3. [Extension Lifecycle](#3-extension-lifecycle)
4. [Extension Composition](#4-extension-composition)
5. [Schema Constraints from Extensions](#5-schema-constraints-from-extensions)
6. [API Specification](#6-api-specification)

---

## 1. Extension Protocol

### Core Principle

The backend exposes exactly one interface: a structured API. There is no "admin panel," no direct SQL access for users, no alternative path. Every interaction — whether a researcher dictating findings or an AI agent querying the graph — goes through an extension that speaks this protocol.

This is not just an architectural preference. It is the mechanism that lets us version, audit, and evolve the backend without breaking downstream consumers. Extensions translate between the messy, multimodal world and the clean semantic graph.

### 1.1 Write Protocol (Input Extensions)

#### Minimum Viable Payload

The atomic unit of knowledge in the system is a **claim**. The minimum viable write is:

```json
{
  "claims": [
    {
      "content": "Compound X reduces inflammation by 40% compared to control",
      "claim_type": "empirical",
      "confidence": 0.85,
      "provenance": {
        "source_type": "voice_dictation",
        "extension_id": "ext-voice-v1",
        "contributor_id": "user-jane-doe",
        "timestamp": "2026-02-08T14:30:00Z",
        "raw_input_ref": "blob://voice/2026-02-08/rec-001.opus"
      }
    }
  ]
}
```

That's it. One claim, one provenance record. Everything else — evidence, relationships, embeddings — is optional at write time but can be attached later.

However, most real submissions will be richer. The general write payload is a **knowledge bundle**: a set of claims, evidence nodes, and relationships that form a coherent unit.

#### Knowledge Bundle Structure

```json
{
  "bundle": {
    "source_context": {
      "extension_id": "ext-paper-ingest-v2",
      "contributor_id": "user-jane-doe",
      "session_id": "sess-abc123",
      "timestamp": "2026-02-08T14:30:00Z",
      "description": "Ingestion of Smith et al. 2025, J. Immunology"
    },
    "claims": [ ... ],
    "evidence": [ ... ],
    "relationships": [ ... ],
    "artifacts": [ ... ]
  }
}
```

A bundle is atomic: either all of it is accepted or none of it is. This is critical for paper ingestion — you don't want half the claims from a paper stored while the other half failed validation.

#### Validation Pipeline

When a bundle arrives, the backend runs it through a validation pipeline:

1. **Structural validation** — Does the payload conform to the schema? Are required fields present? Are IDs well-formed?
2. **Referential integrity** — Do all relationships reference claims/evidence that either exist in the bundle or already exist in the graph?
3. **Provenance validation** — Is the extension registered? Does the contributor have write permission? Is the provenance chain intact?
4. **Duplicate detection** — Does this claim already exist (semantic similarity check via embeddings)? If so, flag as potential duplicate rather than rejecting.
5. **Conflict detection** — Does this claim contradict an existing claim? If so, both claims are stored, but a `contradicts` relationship is created between them. The system does not resolve contradictions — it records them.

The backend does NOT validate truth. It validates structure and provenance. Whether compound X actually reduces inflammation by 40% is not the backend's job. The backend's job is to faithfully record the claim, who made it, what evidence supports it, and what other claims agree or disagree.

#### Conflict Resolution: Record, Don't Resolve

When two extensions submit contradictory claims (e.g., "compound X reduces inflammation" vs. "compound X has no effect on inflammation"), the backend:

1. Stores both claims.
2. Creates a `contradicts` relationship between them.
3. Each claim retains its own provenance, confidence, and evidence links.
4. Output extensions can present contradictions however they want — side-by-side comparison, weighted by evidence strength, sorted by recency, etc.

This design reflects how science actually works: contradictory findings coexist until evidence resolves them. The backend is a faithful record, not an arbiter.

#### Transactional Semantics

- **Single bundle = single transaction.** If any part of a bundle fails validation, the entire bundle is rejected. The response includes specific errors for each failing item.
- **Cross-bundle: eventual consistency.** Two bundles submitted concurrently are processed independently. If bundle A creates claim C1 and bundle B creates a relationship to C1, bundle B might fail if it arrives before A is committed. The extension should retry or use the `pending_refs` mechanism (a relationship can reference a claim by `external_id` that doesn't exist yet, and the backend will resolve it when the target appears within a configurable window).
- **Idempotency.** Every bundle has a client-generated `idempotency_key`. Resubmitting the same bundle is a no-op, not a duplicate.

### 1.2 Read Protocol (Output Extensions)

#### Query Approaches

The read protocol supports three query modes, because different extensions need fundamentally different access patterns:

**1. Direct lookup** — Retrieve a specific node by ID.
```
GET /v1/claims/{claim_id}
```

**2. Graph traversal** — Walk relationships from a starting node.
```json
POST /v1/query/traverse
{
  "start": "claim-abc123",
  "direction": "outgoing",
  "relationship_types": ["supports", "contradicts", "depends_on"],
  "depth": 3,
  "filters": {
    "claim_type": ["empirical", "theoretical"],
    "min_confidence": 0.5
  }
}
```

**3. Semantic search** — Find claims by meaning, not by structure.
```json
POST /v1/query/search
{
  "query": "effect of compound X on inflammation",
  "top_k": 20,
  "filters": {
    "claim_type": ["empirical"],
    "date_range": ["2024-01-01", "2026-12-31"]
  }
}
```

#### Why Not GraphQL or SPARQL?

**GraphQL** is tempting because extensions want flexible subsets of data. But GraphQL's type system assumes a fixed schema shape, and our knowledge graph is inherently heterogeneous (claims about chemistry look different from claims about mathematics). We'd end up with a generic `Node` type that defeats GraphQL's purpose.

**SPARQL** is the academic standard for knowledge graphs, but it's hostile to developers. Every extension author would need to learn a niche query language. The adoption cost kills extensibility.

Our approach: **a REST API with structured query payloads**. This gives us:
- Familiar HTTP semantics for extension developers
- Structured JSON query bodies that are easy to construct programmatically
- Backend freedom to optimize execution (queries are declarative enough)
- Easy to add a GraphQL or SPARQL layer later as an output extension itself

#### Views

An output extension can request a "view" — a pre-defined projection of the knowledge graph tailored to a specific use case:

```json
POST /v1/query/view
{
  "view_type": "paper",
  "root_claims": ["claim-abc", "claim-def", "claim-ghi"],
  "options": {
    "include_evidence": true,
    "include_contradictions": true,
    "citation_style": "apa7",
    "max_depth": 5
  }
}
```

Views are computed server-side and returned as structured documents. The `paper` view returns something that can be rendered as a traditional paper. The `proof_tree` view returns a DAG of proof steps. The `timeline` view returns claims ordered chronologically. Extensions can register new view types.

#### Subscriptions

For real-time updates (e.g., a dashboard that shows new claims in a domain):

```
WebSocket /v1/subscribe
{
  "filters": {
    "claim_type": ["empirical"],
    "topics": ["inflammation", "compound-x"],
    "min_confidence": 0.7
  }
}
```

The backend pushes events (claim_created, claim_updated, relationship_created, etc.) to subscribers whose filters match. This enables live collaboration — one researcher dictating findings while another watches the knowledge graph grow in real time.

### 1.3 Authentication & Authorization

#### Extension Authentication

Extensions authenticate via **API keys** tied to a registered extension identity:

```
Authorization: Bearer ext_key_live_abc123def456
```

Each key is scoped to an extension ID and has:
- **Rate limits** (writes/minute, reads/minute)
- **Capability set** (which API endpoints it can call)
- **Schema scope** (which claim types it can create)

#### User Authentication

Users authenticate through their client application (which hosts the extension). The extension passes a user identity token:

```
X-Contributor-Token: usr_token_xyz789
```

This token is verified against the identity provider. The combination of extension identity + user identity determines permissions.

#### Permission Model

Permissions are layered:

1. **Extension permissions** — What can this extension do? (The voice extension can create empirical claims. The proof verifier can update verification status. The search extension can only read.)
2. **User permissions** — What can this user do? (Authenticated researchers can write. Anonymous users can read public claims. Administrators can delete.)
3. **Claim-level permissions** — Who can see/modify this specific claim? (Default: public read, author write. Can be restricted to a group, institution, or kept private.)

Write-on-behalf-of: An extension always writes on behalf of a user. The provenance record always includes both the extension ID and the contributor ID. An extension cannot write "as itself" — there's always a human (or identified AI agent) in the provenance chain.

---

## 2. Input Extension Deep Dives

### 2.1 Voice/Dictation Extension

#### Scenario
A researcher says: *"I ran the experiment with 50 samples and found that compound X reduces inflammation by 40% compared to control, with p-value 0.003."*

#### Processing Pipeline

```
Audio → Speech-to-Text → NLP Claim Extraction → Structured Bundle → Backend API
```

**Step 1: Audio capture and transcription.**
The extension runs on the researcher's phone or laptop. It captures audio, sends it to a speech-to-text service (Whisper, Deepgram, etc.), and receives raw text.

Raw transcript:
> "I ran the experiment with 50 samples and found that compound X reduces inflammation by 40% compared to control, with p-value 0.003"

**Step 2: Claim extraction via LLM.**
The extension sends the transcript to an LLM with a structured extraction prompt. The prompt instructs the model to identify:
- Claims (what is being asserted)
- Evidence parameters (sample size, effect size, statistical significance)
- Context (what experiment, what conditions)
- Confidence signals (hedging language, certainty markers)

LLM output:
```json
{
  "extracted_claims": [
    {
      "content": "Compound X reduces inflammation by 40% compared to control",
      "claim_type": "empirical",
      "parameters": {
        "sample_size": 50,
        "effect_size": 0.40,
        "effect_direction": "reduction",
        "p_value": 0.003,
        "comparison": "control group"
      },
      "extraction_confidence": 0.95
    }
  ],
  "ambiguities": [],
  "missing_info": ["experiment protocol", "measurement method", "compound X identity"]
}
```

**Step 3: User confirmation (optional).**
The extension can show the extracted claims to the researcher for confirmation. They might add: "This was a randomized controlled trial measuring CRP levels." This enriches the metadata.

**Step 4: Bundle submission.**

```json
POST /v1/bundles
Authorization: Bearer ext_key_live_voice_v1
X-Contributor-Token: usr_token_janedoe

{
  "idempotency_key": "voice-sess-2026-02-08-rec001",
  "bundle": {
    "source_context": {
      "extension_id": "ext-voice-v1",
      "contributor_id": "user-jane-doe",
      "session_id": "voice-sess-2026-02-08",
      "timestamp": "2026-02-08T14:30:00Z",
      "description": "Voice dictation during lab walkback"
    },
    "claims": [
      {
        "temp_id": "tc-1",
        "content": "Compound X reduces inflammation by 40% compared to control",
        "content_embedding_hint": "anti-inflammatory effect compound X 40% reduction",
        "claim_type": "empirical",
        "confidence": 0.85,
        "status": "draft",
        "metadata": {
          "parameters": {
            "sample_size": 50,
            "effect_size": 0.40,
            "effect_direction": "reduction",
            "p_value": 0.003,
            "comparison": "control group"
          },
          "extraction_method": "llm-gpt4",
          "extraction_confidence": 0.95
        },
        "provenance": {
          "source_type": "voice_dictation",
          "raw_input_ref": "blob://voice/2026-02-08/rec-001.opus",
          "transcript": "I ran the experiment with 50 samples and found that compound X reduces inflammation by 40% compared to control, with p-value 0.003"
        }
      }
    ],
    "evidence": [
      {
        "temp_id": "te-1",
        "evidence_type": "experimental_result",
        "content": "RCT with n=50, CRP measurement, p=0.003",
        "metadata": {
          "study_design": "randomized_controlled_trial",
          "sample_size": 50,
          "statistical_test": "unknown",
          "p_value": 0.003
        }
      }
    ],
    "relationships": [
      {
        "source_temp_id": "te-1",
        "target_temp_id": "tc-1",
        "relationship_type": "supports",
        "strength": 0.85
      }
    ]
  }
}
```

**Step 5: Backend response.**

```json
{
  "bundle_id": "bnd-20260208-abc123",
  "status": "accepted",
  "created": {
    "claims": [
      { "temp_id": "tc-1", "id": "claim-f7a8b9c0", "status": "draft" }
    ],
    "evidence": [
      { "temp_id": "te-1", "id": "ev-d3e4f5a6" }
    ],
    "relationships": [
      { "id": "rel-b1c2d3e4", "source": "ev-d3e4f5a6", "target": "claim-f7a8b9c0" }
    ]
  },
  "warnings": [
    {
      "type": "potential_duplicate",
      "claim_temp_id": "tc-1",
      "similar_claim_id": "claim-99887766",
      "similarity": 0.82,
      "message": "Similar claim exists: 'Compound X shows 35% reduction in inflammatory markers'"
    }
  ]
}
```

#### What metadata is captured?

- **Temporal**: timestamp, timezone, recording duration
- **Spatial**: GPS coordinates (if permitted), location name
- **Identity**: speaker ID, extension version
- **Audio quality**: signal-to-noise ratio, confidence from STT
- **Processing chain**: which STT model, which LLM, which extraction prompt version
- **Raw input**: reference to the original audio blob (stored separately)

### 2.2 Paper Ingestion Extension

#### Scenario
Ingesting "Smith et al. 2025" from J. Immunology, a paper with 4 key claims about compound X.

#### Processing Pipeline

```
PDF → Text Extraction → Section Parsing → Claim Extraction → Citation Resolution → Bundle
```

**Step 1: PDF parsing.**
Extract text, figures, tables, and bibliography using a document understanding model (e.g., Nougat, GROBID, or a multimodal LLM). Output: structured sections (abstract, intro, methods, results, discussion, references).

**Step 2: Claim extraction.**
For each section, an LLM extracts claims with their supporting evidence and qualifications. The extraction prompt is tuned per section type — the abstract yields high-level claims, the results section yields specific empirical claims with statistical details, the discussion yields interpretive claims.

**Step 3: Citation resolution.**
For each reference in the paper's bibliography:
- Search the backend for existing claims from that reference (by DOI, title, author match).
- If found: create `cites` relationships to existing claims.
- If not found: create a stub claim with the citation metadata, marked as `unverified_reference`.

**Step 4: Figure/table handling.**
Figures and tables are stored as **artifacts** linked to the claims they support. The extension extracts structured data from tables where possible (e.g., CSV representation). Figures are stored as images with LLM-generated descriptions.

**Step 5: Bundle submission.**

```json
POST /v1/bundles
Authorization: Bearer ext_key_live_paper_v2
X-Contributor-Token: usr_token_janedoe

{
  "idempotency_key": "paper-doi-10.1234/jimm.2025.001",
  "bundle": {
    "source_context": {
      "extension_id": "ext-paper-ingest-v2",
      "contributor_id": "user-jane-doe",
      "session_id": "ingest-smith2025",
      "timestamp": "2026-02-08T15:00:00Z",
      "description": "Ingestion of Smith et al. 2025, J. Immunology, DOI:10.1234/jimm.2025.001"
    },
    "claims": [
      {
        "temp_id": "tc-1",
        "content": "Compound X reduces CRP levels by 40% in human subjects with chronic inflammation",
        "claim_type": "empirical",
        "confidence": 0.90,
        "status": "published",
        "metadata": {
          "parameters": {
            "sample_size": 200,
            "effect_size": 0.40,
            "p_value": 0.001,
            "population": "adults with chronic inflammation",
            "biomarker": "C-reactive protein"
          },
          "paper_section": "results",
          "paper_location": "p.7, paragraph 2"
        },
        "provenance": {
          "source_type": "published_paper",
          "doi": "10.1234/jimm.2025.001",
          "authors": ["Smith, A.", "Jones, B.", "Lee, C."],
          "journal": "Journal of Immunology",
          "year": 2025
        }
      },
      {
        "temp_id": "tc-2",
        "content": "Compound X inhibits NF-kB signaling pathway activation",
        "claim_type": "mechanistic",
        "confidence": 0.80,
        "status": "published",
        "metadata": {
          "pathway": "NF-kB",
          "mechanism": "inhibition",
          "evidence_basis": "in_vitro",
          "paper_section": "results",
          "paper_location": "p.9, Figure 3"
        },
        "provenance": {
          "source_type": "published_paper",
          "doi": "10.1234/jimm.2025.001",
          "authors": ["Smith, A.", "Jones, B.", "Lee, C."],
          "journal": "Journal of Immunology",
          "year": 2025
        }
      },
      {
        "temp_id": "tc-3",
        "content": "The anti-inflammatory effect of Compound X is dose-dependent in the range 10-100mg/kg",
        "claim_type": "empirical",
        "confidence": 0.85,
        "status": "published",
        "metadata": {
          "dose_range": "10-100mg/kg",
          "relationship": "dose-dependent",
          "model": "mouse",
          "paper_section": "results",
          "paper_location": "p.8, Table 2"
        },
        "provenance": {
          "source_type": "published_paper",
          "doi": "10.1234/jimm.2025.001",
          "authors": ["Smith, A.", "Jones, B.", "Lee, C."],
          "journal": "Journal of Immunology",
          "year": 2025
        }
      },
      {
        "temp_id": "tc-4",
        "content": "Compound X represents a promising therapeutic candidate for chronic inflammatory diseases",
        "claim_type": "interpretive",
        "confidence": 0.60,
        "status": "published",
        "metadata": {
          "paper_section": "discussion",
          "paper_location": "p.12, paragraph 1",
          "qualifier": "promising candidate — not yet clinically validated"
        },
        "provenance": {
          "source_type": "published_paper",
          "doi": "10.1234/jimm.2025.001",
          "authors": ["Smith, A.", "Jones, B.", "Lee, C."],
          "journal": "Journal of Immunology",
          "year": 2025
        }
      }
    ],
    "evidence": [
      {
        "temp_id": "te-1",
        "evidence_type": "clinical_trial",
        "content": "Double-blind RCT, n=200, 12-week duration, CRP primary endpoint",
        "metadata": {
          "study_design": "double_blind_rct",
          "sample_size": 200,
          "duration": "12 weeks",
          "primary_endpoint": "CRP"
        }
      },
      {
        "temp_id": "te-2",
        "evidence_type": "in_vitro_experiment",
        "content": "Western blot analysis of NF-kB pathway components in treated HeLa cells",
        "metadata": {
          "technique": "western_blot",
          "cell_line": "HeLa"
        }
      },
      {
        "temp_id": "te-3",
        "evidence_type": "dose_response_study",
        "content": "Mouse model dose-response curve, 5 dose levels, inflammation score endpoint",
        "metadata": {
          "model_organism": "mouse",
          "dose_levels": 5,
          "dose_range": "10-100mg/kg"
        }
      }
    ],
    "relationships": [
      {
        "source_temp_id": "te-1",
        "target_temp_id": "tc-1",
        "relationship_type": "supports",
        "strength": 0.90
      },
      {
        "source_temp_id": "te-2",
        "target_temp_id": "tc-2",
        "relationship_type": "supports",
        "strength": 0.80
      },
      {
        "source_temp_id": "te-3",
        "target_temp_id": "tc-3",
        "relationship_type": "supports",
        "strength": 0.85
      },
      {
        "source_temp_id": "tc-2",
        "target_temp_id": "tc-1",
        "relationship_type": "explains",
        "metadata": { "note": "NF-kB inhibition is proposed mechanism for CRP reduction" }
      },
      {
        "source_temp_id": "tc-1",
        "target_temp_id": "tc-4",
        "relationship_type": "supports",
        "strength": 0.60
      },
      {
        "source_temp_id": "tc-3",
        "target_temp_id": "tc-4",
        "relationship_type": "supports",
        "strength": 0.50
      },
      {
        "target_id": "claim-99887766",
        "source_temp_id": "tc-1",
        "relationship_type": "cites",
        "metadata": { "citation_context": "consistent with prior findings by Wang et al. 2023" }
      }
    ],
    "artifacts": [
      {
        "temp_id": "ta-1",
        "artifact_type": "figure",
        "description": "Figure 3: Western blot showing NF-kB pathway inhibition",
        "storage_ref": "blob://papers/smith2025/fig3.png",
        "linked_claims": ["tc-2"],
        "linked_evidence": ["te-2"]
      },
      {
        "temp_id": "ta-2",
        "artifact_type": "table",
        "description": "Table 2: Dose-response data for Compound X in mouse model",
        "storage_ref": "blob://papers/smith2025/table2.csv",
        "structured_data": {
          "format": "csv",
          "columns": ["dose_mg_kg", "inflammation_score", "std_error", "n"],
          "rows": [
            [10, 7.2, 0.8, 10],
            [25, 5.1, 0.6, 10],
            [50, 3.4, 0.5, 10],
            [75, 2.1, 0.4, 10],
            [100, 1.8, 0.3, 10]
          ]
        },
        "linked_claims": ["tc-3"],
        "linked_evidence": ["te-3"]
      }
    ]
  }
}
```

#### Circular Citations

Papers A and B cite each other. This is handled naturally:
1. Ingest paper A first. It creates a `cites` relationship to paper B, which doesn't exist yet. The relationship uses `pending_ref` with B's DOI.
2. Ingest paper B. It creates claims and a `cites` relationship to paper A's claims (which now exist). The backend also resolves A's pending reference to B's newly created claims.
3. If B is never ingested, the pending reference remains as a stub — a known unknown.

### 2.3 Blackboard Photo Extension

#### Scenario
A researcher photographs a whiteboard containing a mathematical proof that a certain convergence bound holds.

#### Processing Pipeline

```
Photo → Image Enhancement → OCR/LaTeX → Proof Step Extraction → Verification (optional) → Bundle
```

**Step 1: Image preprocessing.**
Clean up the photo: perspective correction, contrast enhancement, noise reduction. This can be done client-side or via a preprocessing service.

**Step 2: OCR to LaTeX.**
Use a math-aware OCR model (e.g., Mathpix, or a fine-tuned vision-language model) to convert the handwritten mathematics into LaTeX. This is the hardest step because handwriting is ambiguous.

OCR output:
```latex
\textbf{Theorem:} \text{For all } \epsilon > 0, \exists N \text{ s.t. } \forall n > N: |a_n - L| < \epsilon

\textbf{Proof:}
\text{Step 1: Let } \epsilon > 0 \text{ be given.}
\text{Step 2: By hypothesis, } |a_n| \leq \frac{M}{n^2} \text{ for all } n.
\text{Step 3: Choose } N > \sqrt{M/\epsilon}.
\text{Step 4: Then for } n > N, |a_n - 0| \leq \frac{M}{n^2} < \frac{M}{N^2} < \epsilon. \quad \square
```

**Step 3: Ambiguity handling.**
The extension flags OCR-ambiguous regions and presents alternatives to the user:
- "Is this `M/n^2` or `M/n^{-2}`?"
- "Is this subscript `n` or `u`?"

The researcher resolves ambiguities interactively. Each resolved ambiguity is recorded in provenance.

**Step 4: Proof step extraction.**
An LLM (or a structured parser for well-known proof patterns) breaks the proof into discrete steps, each of which becomes a claim or subclaim:

```json
{
  "proof_structure": {
    "theorem": "For all epsilon > 0, exists N such that for all n > N: |a_n - L| < epsilon",
    "steps": [
      { "id": "s1", "type": "assumption", "content": "Let epsilon > 0 be given" },
      { "id": "s2", "type": "hypothesis", "content": "|a_n| <= M/n^2 for all n", "depends_on": [] },
      { "id": "s3", "type": "construction", "content": "Choose N > sqrt(M/epsilon)", "depends_on": ["s1", "s2"] },
      { "id": "s4", "type": "deduction", "content": "For n > N: |a_n - 0| <= M/n^2 < M/N^2 < epsilon", "depends_on": ["s2", "s3"] }
    ],
    "conclusion": { "follows_from": ["s4"], "establishes": "theorem" }
  }
}
```

**Step 5: Verification (optional but valuable).**
If the extension has access to a formal verification backend (Lean 4, Coq, Metamath), it can attempt to formalize and verify the proof. This is not always possible (most informal proofs skip steps), but when it succeeds, the claim gets `verification_status: "formally_verified"`.

More commonly, verification is partial: the extension can check that the logical structure is valid (each step follows from its dependencies) even if it can't formalize every step.

**Step 6: Bundle submission.**

```json
POST /v1/bundles
{
  "idempotency_key": "blackboard-2026-02-08-img003",
  "bundle": {
    "source_context": {
      "extension_id": "ext-blackboard-v1",
      "contributor_id": "user-prof-chen",
      "timestamp": "2026-02-08T16:00:00Z",
      "description": "Whiteboard proof of convergence bound, Math 520 office"
    },
    "claims": [
      {
        "temp_id": "tc-thm",
        "content": "For all epsilon > 0, there exists N such that for all n > N: |a_n - L| < epsilon",
        "content_latex": "\\forall \\epsilon > 0, \\exists N \\text{ s.t. } \\forall n > N: |a_n - L| < \\epsilon",
        "claim_type": "theorem",
        "confidence": 0.95,
        "status": "draft",
        "verification_status": "unverified",
        "provenance": {
          "source_type": "blackboard_photo",
          "raw_input_ref": "blob://photos/2026-02-08/img003.jpg",
          "ocr_model": "mathpix-v3",
          "ocr_confidence": 0.88,
          "ambiguities_resolved": 2
        }
      },
      {
        "temp_id": "tc-s2",
        "content": "|a_n| <= M/n^2 for all n",
        "content_latex": "|a_n| \\leq \\frac{M}{n^2} \\text{ for all } n",
        "claim_type": "hypothesis",
        "confidence": 0.95,
        "status": "draft"
      },
      {
        "temp_id": "tc-s3",
        "content": "Choosing N > sqrt(M/epsilon) satisfies the convergence criterion",
        "content_latex": "N > \\sqrt{M/\\epsilon}",
        "claim_type": "construction",
        "confidence": 0.95,
        "status": "draft"
      },
      {
        "temp_id": "tc-s4",
        "content": "For n > N: |a_n - 0| <= M/n^2 < M/N^2 < epsilon",
        "content_latex": "\\forall n > N: |a_n - 0| \\leq \\frac{M}{n^2} < \\frac{M}{N^2} < \\epsilon",
        "claim_type": "deduction",
        "confidence": 0.95,
        "status": "draft"
      }
    ],
    "relationships": [
      {
        "source_temp_id": "tc-s2",
        "target_temp_id": "tc-s3",
        "relationship_type": "depends_on"
      },
      {
        "source_temp_id": "tc-s3",
        "target_temp_id": "tc-s4",
        "relationship_type": "depends_on"
      },
      {
        "source_temp_id": "tc-s2",
        "target_temp_id": "tc-s4",
        "relationship_type": "depends_on"
      },
      {
        "source_temp_id": "tc-s4",
        "target_temp_id": "tc-thm",
        "relationship_type": "proves"
      }
    ],
    "artifacts": [
      {
        "temp_id": "ta-1",
        "artifact_type": "photo",
        "description": "Original whiteboard photo",
        "storage_ref": "blob://photos/2026-02-08/img003.jpg",
        "linked_claims": ["tc-thm"]
      },
      {
        "temp_id": "ta-2",
        "artifact_type": "latex_source",
        "description": "Full LaTeX of proof as extracted by OCR",
        "content_inline": "\\textbf{Theorem:} ...",
        "linked_claims": ["tc-thm", "tc-s2", "tc-s3", "tc-s4"]
      }
    ]
  }
}
```

### 2.4 Search/Query Extension (Output)

#### Scenario
A researcher asks: *"What is known about compound X's effect on inflammation?"*

#### Processing Pipeline

```
Natural Language Query → Query Understanding → Hybrid Search → Result Assembly → Response
```

**Step 1: Query understanding.**
The extension parses the natural language query into a structured search plan:

```json
{
  "interpreted_query": {
    "entities": ["compound X", "inflammation"],
    "relationship_sought": "effect",
    "query_type": "exploratory",
    "strategy": ["semantic_search", "graph_traversal"]
  }
}
```

**Step 2: Semantic search.**
The extension issues a semantic search to find claims whose embeddings are close to the query:

```json
POST /v1/query/search
{
  "query": "compound X effect on inflammation",
  "top_k": 50,
  "filters": {
    "claim_type": ["empirical", "mechanistic", "interpretive"]
  }
}
```

Response (abbreviated):
```json
{
  "results": [
    {
      "claim_id": "claim-f7a8b9c0",
      "content": "Compound X reduces CRP levels by 40% in human subjects with chronic inflammation",
      "claim_type": "empirical",
      "confidence": 0.90,
      "similarity_score": 0.94,
      "provenance_summary": "Smith et al. 2025, J. Immunology"
    },
    {
      "claim_id": "claim-aabb1122",
      "content": "Compound X inhibits NF-kB signaling pathway activation",
      "claim_type": "mechanistic",
      "confidence": 0.80,
      "similarity_score": 0.87,
      "provenance_summary": "Smith et al. 2025, J. Immunology"
    },
    {
      "claim_id": "claim-99887766",
      "content": "Compound X shows 35% reduction in inflammatory markers in mouse model",
      "claim_type": "empirical",
      "confidence": 0.85,
      "similarity_score": 0.85,
      "provenance_summary": "Wang et al. 2023, Inflammation Research"
    }
  ],
  "total_matches": 12
}
```

**Step 3: Graph traversal for context.**
For top results, the extension walks the graph to gather supporting evidence, contradicting claims, and dependency chains:

```json
POST /v1/query/traverse
{
  "start": "claim-f7a8b9c0",
  "direction": "both",
  "relationship_types": ["supports", "contradicts", "explains", "depends_on", "cites"],
  "depth": 2
}
```

This returns the local neighborhood: the evidence nodes supporting the claim, any contradicting claims, the mechanism that explains it, and citations.

**Step 4: Result assembly.**
The extension assembles a human-readable response, organized by theme:

```
## What is known about Compound X's effect on inflammation

### Strong evidence (high confidence, multiple sources)
- **Compound X reduces CRP levels by ~35-40% in chronic inflammation**
  - Smith et al. 2025 (human RCT, n=200, p<0.001): 40% reduction
  - Wang et al. 2023 (mouse model, n=50): 35% reduction
  - Effect is dose-dependent in range 10-100mg/kg (Smith 2025)

### Proposed mechanism
- **Compound X inhibits NF-kB signaling pathway** (Smith 2025, in vitro)
  - This would explain the CRP reduction, since NF-kB regulates CRP expression

### Open questions
- No human dose-response data (only mouse model)
- Long-term effects unknown (longest study: 12 weeks)
- No replication by independent groups yet

### Contradictions
- None found for the primary claim

[12 claims found, 3 sources, confidence range: 0.60-0.90]
```

**Step 5: Ranking.**
Results are ranked by a weighted combination of:
- Semantic similarity to the query (embedding distance)
- Confidence score of the claim
- Evidence strength (number and quality of supporting evidence nodes)
- Recency (more recent claims ranked higher, all else equal)
- Provenance quality (peer-reviewed > preprint > dictation)

The ranking weights are configurable by the output extension, so a "rigorous review" extension might weight evidence strength heavily while a "quick discovery" extension might weight recency and semantic similarity.

---

## 3. Extension Lifecycle

### 3.1 Registration

Extensions are registered via a manifest file:

```json
{
  "extension_id": "ext-voice-v1",
  "name": "Voice Dictation Input",
  "version": "1.0.0",
  "type": "input",
  "description": "Captures voice dictation and extracts structured claims",
  "author": "Knowledge Backend Team",
  "capabilities": {
    "can_write": true,
    "can_read": false,
    "claim_types": ["empirical", "observational"],
    "creates_artifacts": true,
    "requires_user_auth": true
  },
  "api_version_required": "v1",
  "webhook_url": "https://voice-ext.example.com/webhook",
  "health_check_url": "https://voice-ext.example.com/health"
}
```

Registration process:
1. Extension developer submits manifest to the backend admin API.
2. Backend validates the manifest, provisions API keys, and stores the registration.
3. Extension receives its API key and can begin making requests.
4. Backend periodically pings the health check URL. Extensions that fail health checks for >24h are marked inactive.

### 3.2 Discovery

Extensions are discoverable via a registry endpoint:

```
GET /v1/extensions?type=input&status=active
```

This returns a list of registered extensions with their capabilities. A client application can use this to offer users a menu of available input/output methods.

### 3.3 Versioning

**Extension versioning** and **backend schema versioning** are independent:

- The backend API is versioned (`/v1/`, `/v2/`). Breaking schema changes get a new version.
- Extensions declare which API version they require. The backend can serve multiple API versions simultaneously.
- Extensions have their own semver. A new version of the voice extension can be deployed without touching the backend.

**Migration path when the backend schema changes:**
1. New API version is deployed alongside the old one.
2. Extensions continue working on the old API version.
3. Extension developers update to the new API version at their own pace.
4. Old API version is deprecated (with a long sunset period, minimum 6 months) and eventually removed.

### 3.4 Can Extensions Modify the Schema?

No. Extensions cannot add new entity types, relationship types, or fields to the core schema. This is a deliberate constraint: the schema is the contract that all extensions share, and unilateral modification would break other extensions.

However, extensions CAN:
- Use the `metadata` field (a JSON blob) on any entity to store extension-specific data.
- Propose new claim types or relationship types to the schema governance process.
- Register **custom views** that define how their specific metadata is interpreted.

The `metadata` field is the escape hatch. It's schemaless by design. The voice extension can store `{"ocr_confidence": 0.88}` without the paper ingestion extension needing to know about it. Schema evolution happens when a pattern in metadata becomes so common that it deserves a first-class field.

---

## 4. Extension Composition

### 4.1 Pipelines

Extensions can be composed into pipelines. The voice extension doesn't need to handle claim extraction itself — it can delegate to a "claim extraction" extension:

```
Voice Extension → Claim Extraction Extension → Verification Extension → Backend
```

This is implemented as a **pipeline**, defined in a pipeline manifest:

```json
{
  "pipeline_id": "voice-to-verified-claim",
  "stages": [
    {
      "extension_id": "ext-voice-v1",
      "role": "source",
      "output_format": "raw_transcript"
    },
    {
      "extension_id": "ext-claim-extract-v1",
      "role": "transform",
      "input_format": "raw_transcript",
      "output_format": "knowledge_bundle"
    },
    {
      "extension_id": "ext-proof-verify-v1",
      "role": "enrich",
      "input_format": "knowledge_bundle",
      "output_format": "knowledge_bundle",
      "optional": true
    }
  ],
  "sink": "backend"
}
```

The pipeline orchestrator (a lightweight service) manages the flow. If a stage fails, the pipeline can be configured to skip optional stages or abort entirely.

### 4.2 Event-Driven Composition

Alternatively, extensions can react to backend events rather than being explicitly chained:

```
Voice Extension → writes claim to Backend
                      ↓ (event: claim_created)
Verification Extension → reads claim, attempts verification, updates verification_status
                      ↓ (event: claim_verified)
Notification Extension → notifies the researcher that their claim was verified
```

This is more loosely coupled than pipelines. Extensions subscribe to events via the WebSocket subscription API and act autonomously. The backend doesn't need to know about the composition — each extension independently decides what events to react to.

### 4.3 Pipeline vs Event-Driven

Use **pipelines** when:
- The processing steps are known in advance.
- Each step must complete before the next begins.
- The entire chain must succeed or fail atomically.

Use **event-driven** when:
- Extensions are independently developed and deployed.
- Processing is asynchronous and non-blocking.
- Multiple independent extensions react to the same event.
- The composition is emergent rather than designed.

Both patterns coexist. A voice extension might use a pipeline for initial processing, while a verification extension operates event-driven in the background.

### 4.4 Inter-Extension Communication

Extensions do NOT communicate directly. All communication goes through the backend:
1. Extension A writes data to the backend.
2. Backend emits an event.
3. Extension B reads the event and the associated data from the backend.

This ensures the backend remains the single source of truth. No extension has a private channel to another extension. Every piece of information flows through the graph.

---

## 5. Schema Constraints from Extensions

Based on the extension deep dives above, here are the concrete schema requirements that the schema architect must accommodate:

### 5.1 Required Entity Types

**Claims** must support:
- `content` (text, the natural language statement)
- `content_latex` (optional LaTeX representation for mathematical claims)
- `content_embedding` (vector embedding for semantic search, computed by the backend)
- `claim_type` (enum: empirical, theoretical, mechanistic, interpretive, hypothesis, theorem, lemma, construction, deduction, observational, ...) — this must be **extensible**, not a fixed enum
- `confidence` (float 0-1)
- `status` (draft, published, retracted, superseded)
- `verification_status` (unverified, partially_verified, formally_verified, disputed)
- `metadata` (JSON blob for extension-specific data)
- `provenance` (see below)
- `created_at`, `updated_at`, `version`

**Evidence** must support:
- `evidence_type` (experimental_result, clinical_trial, in_vitro_experiment, observational_study, simulation, mathematical_proof, ...)
- `content` (text description)
- `metadata` (JSON blob for structured parameters: sample_size, p_value, etc.)
- `provenance`

**Relationships** must support:
- `source` (claim or evidence ID)
- `target` (claim or evidence ID)
- `relationship_type` (supports, contradicts, depends_on, explains, proves, cites, supersedes, refines, ...)
- `strength` (optional float 0-1, for weighted relationships)
- `metadata` (JSON blob)

**Artifacts** must support:
- `artifact_type` (figure, table, photo, audio, video, latex_source, code, dataset, ...)
- `description` (text)
- `storage_ref` (URI to blob storage)
- `content_inline` (optional, for small artifacts stored directly)
- `structured_data` (optional, for tables/datasets with parseable content)
- Links to claims and evidence

**Provenance** must support:
- `source_type` (voice_dictation, published_paper, blackboard_photo, code_analysis, conversation, ...)
- `extension_id`
- `contributor_id`
- `timestamp`
- `raw_input_ref` (URI to the original input)
- `processing_chain` (list of processing steps: which models, which versions, which prompts)
- Paper-specific: `doi`, `authors`, `journal`, `year`

### 5.2 Things the Schema Architect Might Miss

1. **`content_latex` on claims.** Mathematical claims need a LaTeX field alongside the natural language content. This is not just for display — it's the basis for formal verification. If this is relegated to `metadata`, it becomes invisible to the verification pipeline.

2. **Pending references.** Relationships must be able to reference entities that don't exist yet, identified by external ID (DOI, URL, etc.). This is essential for paper ingestion where circular citations are common and papers are ingested in arbitrary order.

3. **Temp IDs within bundles.** The bundle submission format needs a temporary ID system so that relationships within a bundle can reference other items in the same bundle before they have real IDs. The backend maps temp IDs to real IDs atomically.

4. **Extraction confidence vs. claim confidence.** These are different. Claim confidence is "how confident are we in the claim's truth?" Extraction confidence is "how confident is the extension that it correctly extracted the claim from the source?" Both need to be stored. Extraction confidence belongs in provenance; claim confidence is a first-class field on the claim.

5. **Ambiguity records.** The blackboard extension needs to record OCR ambiguities that were resolved. This is part of provenance and affects trust: a claim whose LaTeX was ambiguous and human-resolved is more trustworthy than one where the system guessed.

6. **Artifact-to-claim links are many-to-many.** A figure might support multiple claims. A claim might be supported by multiple figures. This is a junction table, not a foreign key.

7. **Claim versioning needs to be explicit.** When a claim is updated (e.g., a researcher refines their dictated claim), the old version must be preserved and linked to the new version via a `supersedes` relationship. This is history, not just an `updated_at` timestamp.

8. **Relationship directionality matters.** "A supports B" is not the same as "B supports A." Relationships are directed. Some relationship types are inherently directional (supports, proves, depends_on) while others could be symmetric (contradicts, related_to). The schema should capture this.

9. **Batch/bundle provenance vs. individual provenance.** A paper ingestion creates a bundle with one source context but many claims. Each claim inherits the bundle's provenance but may have additional claim-specific provenance (e.g., which page, which section). The schema needs both bundle-level and item-level provenance.

10. **The `metadata` field must be indexed.** Extensions store structured parameters in metadata (sample_size, p_value, etc.). If metadata is just an opaque JSON blob, you can't query "all claims with p_value < 0.05." Consider JSONB with GIN indexing (PostgreSQL) or a secondary index strategy.

### 5.3 Extension Patterns That Require Specific Schema Features

| Extension Pattern | Schema Requirement |
|---|---|
| Voice dictation stores audio refs | Artifact entity with blob storage URIs |
| Paper ingestion extracts structured table data | Artifact with `structured_data` (parseable format) |
| Blackboard OCR has ambiguity | Provenance must store `ambiguities_resolved` |
| Proof verification updates claims | `verification_status` field, updateable by specific extensions |
| Search ranks by evidence strength | Evidence must link to claims with queryable `strength` |
| Multiple extensions extract same claim | Duplicate detection via embedding similarity; `similar_to` relationships |
| Pipelines need atomic batch writes | Bundle/transaction support at the API level |
| Event-driven extensions need notifications | Event log / changelog on all entities |
| Claims evolve over time | Version chain via `supersedes` relationships |
| Cross-paper citation resolution | External ID fields (DOI, URL) on claims for reference resolution |

---

## 6. API Specification

### Base URL
```
https://api.knowledge-backend.example.com/v1
```

### Authentication
All requests require:
```
Authorization: Bearer <extension_api_key>
X-Contributor-Token: <user_token>  (for write operations)
```

### 6.1 Submit a Knowledge Bundle

```
POST /v1/bundles
Content-Type: application/json
```

**Request body:** (see full examples in Section 2 above)

**Response — success (201 Created):**
```json
{
  "bundle_id": "bnd-20260208-abc123",
  "status": "accepted",
  "created": {
    "claims": [
      { "temp_id": "tc-1", "id": "claim-f7a8b9c0", "status": "draft" }
    ],
    "evidence": [
      { "temp_id": "te-1", "id": "ev-d3e4f5a6" }
    ],
    "relationships": [
      { "id": "rel-b1c2d3e4", "source": "ev-d3e4f5a6", "target": "claim-f7a8b9c0" }
    ],
    "artifacts": [
      { "temp_id": "ta-1", "id": "art-e5f6a7b8" }
    ]
  },
  "warnings": [
    {
      "type": "potential_duplicate",
      "claim_temp_id": "tc-1",
      "similar_claim_id": "claim-99887766",
      "similarity": 0.82,
      "message": "Similar claim exists"
    }
  ]
}
```

**Response — validation failure (422 Unprocessable Entity):**
```json
{
  "status": "rejected",
  "errors": [
    {
      "type": "invalid_reference",
      "item_type": "relationship",
      "detail": "target_id 'claim-nonexistent' does not exist and is not a temp_id in this bundle",
      "path": "bundle.relationships[2].target_id"
    },
    {
      "type": "missing_field",
      "item_type": "claim",
      "detail": "Field 'content' is required",
      "path": "bundle.claims[1].content"
    }
  ]
}
```

**Response — idempotent replay (200 OK):**
```json
{
  "bundle_id": "bnd-20260208-abc123",
  "status": "already_accepted",
  "created": { ... }
}
```

### 6.2 Get a Claim

```
GET /v1/claims/{claim_id}
```

**Response (200 OK):**
```json
{
  "id": "claim-f7a8b9c0",
  "content": "Compound X reduces CRP levels by 40% in human subjects with chronic inflammation",
  "content_latex": null,
  "claim_type": "empirical",
  "confidence": 0.90,
  "status": "published",
  "verification_status": "unverified",
  "metadata": {
    "parameters": {
      "sample_size": 200,
      "effect_size": 0.40,
      "p_value": 0.001
    }
  },
  "provenance": {
    "source_type": "published_paper",
    "extension_id": "ext-paper-ingest-v2",
    "contributor_id": "user-jane-doe",
    "doi": "10.1234/jimm.2025.001",
    "authors": ["Smith, A.", "Jones, B.", "Lee, C."],
    "timestamp": "2026-02-08T15:00:00Z"
  },
  "bundle_id": "bnd-20260208-abc123",
  "created_at": "2026-02-08T15:00:01Z",
  "updated_at": "2026-02-08T15:00:01Z",
  "version": 1
}
```

### 6.3 List Claims

```
GET /v1/claims?claim_type=empirical&status=published&limit=20&offset=0
```

Supports filtering by any first-class field. JSONB metadata fields can be filtered via dot notation:

```
GET /v1/claims?metadata.parameters.p_value__lt=0.05&claim_type=empirical
```

### 6.4 Semantic Search

```
POST /v1/query/search
```

**Request:**
```json
{
  "query": "effect of compound X on inflammation",
  "top_k": 20,
  "filters": {
    "claim_type": ["empirical", "mechanistic"],
    "status": ["published", "draft"],
    "date_range": {
      "from": "2024-01-01",
      "to": "2026-12-31"
    },
    "min_confidence": 0.5
  },
  "include": ["provenance", "evidence_summary"]
}
```

**Response (200 OK):**
```json
{
  "results": [
    {
      "claim": {
        "id": "claim-f7a8b9c0",
        "content": "Compound X reduces CRP levels by 40% in human subjects with chronic inflammation",
        "claim_type": "empirical",
        "confidence": 0.90,
        "status": "published"
      },
      "similarity_score": 0.94,
      "provenance": {
        "source_type": "published_paper",
        "doi": "10.1234/jimm.2025.001",
        "authors": ["Smith, A.", "Jones, B.", "Lee, C."]
      },
      "evidence_summary": {
        "supporting": 3,
        "contradicting": 0,
        "total_relationships": 5
      }
    }
  ],
  "total_matches": 12,
  "query_embedding_used": true
}
```

### 6.5 Graph Traversal

```
POST /v1/query/traverse
```

**Request:**
```json
{
  "start": "claim-f7a8b9c0",
  "direction": "both",
  "relationship_types": ["supports", "contradicts", "explains"],
  "depth": 2,
  "filters": {
    "min_confidence": 0.5
  },
  "include": ["provenance"]
}
```

**Response (200 OK):**
```json
{
  "root": "claim-f7a8b9c0",
  "nodes": [
    {
      "id": "claim-f7a8b9c0",
      "type": "claim",
      "content": "Compound X reduces CRP levels by 40%...",
      "depth": 0
    },
    {
      "id": "ev-d3e4f5a6",
      "type": "evidence",
      "content": "Double-blind RCT, n=200, 12-week duration",
      "depth": 1
    },
    {
      "id": "claim-aabb1122",
      "type": "claim",
      "content": "Compound X inhibits NF-kB signaling pathway",
      "depth": 1
    },
    {
      "id": "claim-99887766",
      "type": "claim",
      "content": "Compound X shows 35% reduction in inflammatory markers in mouse model",
      "depth": 2
    }
  ],
  "edges": [
    {
      "id": "rel-b1c2d3e4",
      "source": "ev-d3e4f5a6",
      "target": "claim-f7a8b9c0",
      "relationship_type": "supports",
      "strength": 0.90
    },
    {
      "id": "rel-c3d4e5f6",
      "source": "claim-aabb1122",
      "target": "claim-f7a8b9c0",
      "relationship_type": "explains"
    },
    {
      "id": "rel-778899aa",
      "source": "claim-99887766",
      "target": "claim-f7a8b9c0",
      "relationship_type": "supports",
      "strength": 0.70
    }
  ],
  "truncated": false,
  "total_nodes_traversed": 4
}
```

### 6.6 Request a View

```
POST /v1/query/view
```

**Request:**
```json
{
  "view_type": "paper",
  "root_claims": ["claim-f7a8b9c0", "claim-aabb1122", "claim-ccdd3344", "claim-eeff5566"],
  "options": {
    "include_evidence": true,
    "include_contradictions": true,
    "citation_style": "apa7",
    "max_depth": 5,
    "title": "The Anti-Inflammatory Properties of Compound X: A Synthesis"
  }
}
```

**Response (200 OK):**
```json
{
  "view_type": "paper",
  "content": {
    "title": "The Anti-Inflammatory Properties of Compound X: A Synthesis",
    "sections": [
      {
        "heading": "Key Findings",
        "claims": ["claim-f7a8b9c0", "claim-aabb1122"],
        "narrative": "Compound X has been shown to reduce CRP levels by 40% in human subjects with chronic inflammation (Smith et al., 2025). The proposed mechanism involves inhibition of the NF-kB signaling pathway...",
        "evidence_cited": ["ev-d3e4f5a6", "ev-e5f6a7b8"]
      }
    ],
    "references": [
      {
        "formatted": "Smith, A., Jones, B., & Lee, C. (2025). ...",
        "doi": "10.1234/jimm.2025.001",
        "claim_ids": ["claim-f7a8b9c0", "claim-aabb1122"]
      }
    ],
    "contradictions": [],
    "metadata": {
      "claims_included": 4,
      "sources_cited": 3,
      "generated_at": "2026-02-08T16:30:00Z"
    }
  }
}
```

### 6.7 Update a Claim

```
PATCH /v1/claims/{claim_id}
```

**Request:**
```json
{
  "confidence": 0.95,
  "verification_status": "partially_verified",
  "metadata": {
    "verification_note": "Proof structure validated; individual steps not formally verified"
  },
  "provenance_addendum": {
    "extension_id": "ext-proof-verify-v1",
    "action": "verification_update",
    "timestamp": "2026-02-08T17:00:00Z"
  }
}
```

**Response (200 OK):**
```json
{
  "id": "claim-f7a8b9c0",
  "version": 2,
  "previous_version": 1,
  "updated_fields": ["confidence", "verification_status", "metadata"],
  "updated_at": "2026-02-08T17:00:01Z"
}
```

Updates create a new version. The previous version is preserved and accessible via:
```
GET /v1/claims/{claim_id}/versions
GET /v1/claims/{claim_id}/versions/{version_number}
```

### 6.8 Subscribe to Events

```
WebSocket wss://api.knowledge-backend.example.com/v1/subscribe
```

**Subscribe message:**
```json
{
  "action": "subscribe",
  "filters": {
    "event_types": ["claim_created", "claim_updated", "relationship_created"],
    "claim_type": ["empirical"],
    "topics": ["inflammation"]
  }
}
```

**Event message (pushed by server):**
```json
{
  "event_type": "claim_created",
  "timestamp": "2026-02-08T14:30:01Z",
  "claim": {
    "id": "claim-f7a8b9c0",
    "content": "Compound X reduces CRP levels by 40%...",
    "claim_type": "empirical",
    "confidence": 0.90
  },
  "bundle_id": "bnd-20260208-abc123",
  "extension_id": "ext-paper-ingest-v2"
}
```

### 6.9 Extension Registration

```
POST /v1/extensions/register
Content-Type: application/json
Authorization: Bearer admin_key_xxx
```

**Request:**
```json
{
  "extension_id": "ext-voice-v1",
  "name": "Voice Dictation Input",
  "version": "1.0.0",
  "type": "input",
  "description": "Captures voice dictation and extracts structured claims",
  "capabilities": {
    "can_write": true,
    "can_read": false,
    "claim_types": ["empirical", "observational"],
    "creates_artifacts": true
  },
  "api_version_required": "v1",
  "webhook_url": "https://voice-ext.example.com/webhook",
  "health_check_url": "https://voice-ext.example.com/health"
}
```

**Response (201 Created):**
```json
{
  "extension_id": "ext-voice-v1",
  "api_key": "ext_key_live_abc123def456",
  "status": "active",
  "registered_at": "2026-02-08T10:00:00Z"
}
```

### 6.10 Error Format

All errors follow a consistent format:

```json
{
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "Bundle validation failed with 2 errors",
    "details": [ ... ],
    "request_id": "req-abc123",
    "timestamp": "2026-02-08T14:30:00Z"
  }
}
```

Error codes:
- `VALIDATION_FAILED` (422) — Bundle or request failed structural validation
- `UNAUTHORIZED` (401) — Invalid or missing API key
- `FORBIDDEN` (403) — Valid API key but insufficient permissions
- `NOT_FOUND` (404) — Requested entity does not exist
- `CONFLICT` (409) — Idempotency key collision with different payload
- `RATE_LIMITED` (429) — Too many requests
- `INTERNAL_ERROR` (500) — Backend failure

---

## Summary of Key Design Decisions

1. **REST with structured query payloads** over GraphQL or SPARQL — developer familiarity wins.
2. **Bundles as the atomic write unit** — a coherent set of claims, evidence, and relationships submitted and validated together.
3. **Record contradictions, don't resolve them** — the backend is a faithful record, not an arbiter of truth.
4. **Extensions never communicate directly** — all data flows through the backend graph.
5. **`metadata` as the schema escape hatch** — extension-specific data lives in JSON blobs; patterns that prove common graduate to first-class fields.
6. **Provenance is mandatory and immutable** — every claim traces back to a source, an extension, and a contributor.
7. **Event-driven composition for loose coupling, pipelines for tight coupling** — both patterns coexist.
8. **Dual confidence model** — extraction confidence (did we read the source correctly?) is separate from claim confidence (is the claim true?).
