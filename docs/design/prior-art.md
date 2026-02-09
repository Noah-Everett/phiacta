# Prior Art: Systems for Structuring Scientific Knowledge

A comprehensive analysis of existing systems that attempt to structure, represent, and share scientific knowledge. This research informs the schema design for the Knowledge Backend.

---

## 1. Semantic Scholar

**What it is:** AI-powered academic search engine by the Allen Institute for AI, covering 214M+ papers across all disciplines. Provides an Academic Graph API for programmatic access.

### Core Data Model

The central entity is the **Paper**, represented as a flat JSON object with selectable fields. The API uses a `fields` query parameter so clients only request what they need.

**Paper fields:**

| Field | Type | Description |
|-------|------|-------------|
| `paperId` | string | Unique S2 identifier (always returned) |
| `title` | string | Paper title (always returned) |
| `abstract` | string | Paper abstract |
| `year` | int | Publication year |
| `venue` | string | Publication venue name |
| `publicationVenue` | object | Detailed venue (id, name, type, ISSN) |
| `publicationDate` | string | Date of publication |
| `authors` | array | List of `{authorId, name}` objects |
| `citationCount` | int | Number of citations |
| `influentialCitationCount` | int | Influential citations (S2 metric) |
| `openAccessPdf` | object | URL to open access PDF |
| `s2FieldsOfStudy` | array | AI-classified fields of study |
| `externalIds` | object | DOI, ArXiv, MAG, ACL, PMID, PMCID, CorpusId |
| `citations` | array | List of citing papers |
| `references` | array | List of referenced papers |
| `tldr` | object | AI-generated summary |
| `publicationTypes` | array | Types (journal article, conference, etc.) |
| `embedding` | object | SPECTER2 vector embedding |

**Author fields:** `authorId`, `name`, `affiliations`, `homepage`, `paperCount`, `citationCount`, `hIndex`

**Citation/Reference fields:** Nested paper objects with optional `contexts` (text around citation), `intents` (methodology, background, result comparison), and `isInfluential` boolean.

**Additional datasets available in bulk:**
- S2ORC: Full text with structural annotations (section headings, paragraphs, inline citation mentions, table/figure references)
- Embeddings: SPECTER vector embeddings per paper
- TLDRs: AI-generated summaries

### How It Handles Key Concerns

- **Claims:** Not represented. The unit of knowledge is the *paper*, not individual claims. TLDRs provide a single-sentence summary but do not decompose papers into claims.
- **Evidence:** Citations are classified by *intent* (background, methodology, result comparison) and *influence*, but there is no structured evidence model.
- **Provenance:** External IDs (DOI, ArXiv, etc.) link to source documents. No provenance for individual facts.
- **Confidence:** `influentialCitationCount` is a proxy for impact, not epistemic confidence. No uncertainty model.
- **Versioning:** ArXiv versions tracked via external IDs, but no first-class versioning.
- **Relationships:** Citation graph only. No typed semantic relationships between papers beyond citing/cited-by.

### What Works Well

- Massive scale (214M+ papers) with good coverage across disciplines
- AI-augmented features (TLDRs, citation intent classification, SPECTER embeddings) add semantic value on top of raw metadata
- Clean REST API with flexible field selection -- good API design pattern
- Open datasets for bulk analysis
- External ID mapping (DOI, ArXiv, PMID, etc.) provides good interoperability

### What's Missing or Broken

- **Paper-centric, not claim-centric.** The atomic unit is a paper, which bundles dozens of claims, methods, and findings into one opaque object. You cannot query "what evidence exists for claim X" -- only "what papers cite paper Y."
- **No structured knowledge extraction.** Despite having full text (S2ORC), claims are not decomposed or formalized. The knowledge is still locked in natural language.
- **No disagreement model.** Two papers making contradictory claims about the same phenomenon are just two nodes in a citation graph. There is no way to represent or query the contradiction.
- **No confidence or verification.** A retracted paper and a Nature paper have the same schema. `influentialCitationCount` is a popularity metric, not an epistemic one.
- **No provenance for claims.** You know a paper exists, but not which specific experiments, datasets, or reasoning support which specific conclusions.

### Lessons for Our Design

1. **Selectable field patterns** are excellent API design -- adopt this. Clients should not be forced to download entire objects.
2. **AI-augmented metadata** (TLDRs, embeddings, citation intent) adds real value. Plan for AI-generated annotations as first-class features, not afterthoughts.
3. **External ID mapping** is critical for interoperability. Support DOI, ArXiv, ORCID, etc. from day one.
4. **Papers are the wrong atomic unit.** The entire system is limited by treating a 20-page document as an indivisible entity. Claims must be the atom.

---

## 2. Knowledge Graphs: Wikidata, DBpedia, Google Knowledge Graph

### 2a. Wikidata

**What it is:** A free, collaborative, multilingual knowledge base operated by the Wikimedia Foundation. Contains 100M+ items, edited by humans and bots, queryable via SPARQL.

**Core Data Model:**

The fundamental structure is: **Item** -> **Statement** -> **Value**, with rich metadata on each statement.

```
Item (Q-id)
  └── Statement
        ├── Claim (core assertion)
        │     ├── Property (P-id) + Value (Snak)
        │     └── Qualifiers (additional property-value pairs)
        ├── References (sets of property-value pairs citing sources)
        └── Rank (preferred / normal / deprecated)
```

**Entity types:**
- **Items** (Q-ids): Things in the world (e.g., Q42 = Douglas Adams)
- **Properties** (P-ids): Relationship types (e.g., P31 = "instance of")
- **Lexemes** (L-ids): Words with grammatical information

**Snak types:** `value` (specific value), `somevalue` (unknown value exists), `novalue` (explicitly no value)

**Qualifier categories:** validity (temporal scope), causality, sequence, annotations, provenance

**How it handles key concerns:**
- **Claims:** First-class. Every statement IS a claim (subject-property-value triple).
- **Evidence:** References are sets of snaks (property-value pairs) that cite sources. E.g., `stated in: Nature`, `page: 42`, `retrieved: 2024-01-15`.
- **Provenance:** Two layers: (1) References on statements cite external sources; (2) Edit history tracks who made each change and when.
- **Confidence:** The **rank** system (preferred/normal/deprecated) is a coarse confidence signal. No numeric confidence scores. `somevalue` and `novalue` handle uncertainty.
- **Versioning:** Full edit history preserved. Statements can be deprecated rather than deleted.
- **Relationships:** Properties define typed, directional relationships. The ontology is community-governed.

**What works well:**
- Statement-level provenance via references is exactly the right granularity
- Qualifier system is elegant -- attaching context (time, place, method) to individual claims
- Rank system handles superseded knowledge gracefully (deprecated, not deleted)
- `somevalue`/`novalue` explicitly represent uncertainty and absence
- Community-governed ontology evolves with knowledge

**What's missing or broken:**
- Designed for *encyclopedic facts*, not *scientific claims*. "Berlin population is 3.7M" works; "compound X inhibits pathway Y with p < 0.05 in mouse model Z" does not fit the same mold.
- No support for complex, multi-step reasoning or proof structures
- Qualifiers are limited to simple property-value pairs -- cannot express conditional claims, probability distributions, or experimental contexts
- No vector embeddings or semantic search -- relies on exact property matching
- Consensus-driven model (one "preferred" rank) does not handle genuine scientific disagreement well

### 2b. DBpedia

**What it is:** Structured data extracted automatically from Wikipedia infoboxes. Contains 228M+ entities, 9.5B RDF triples.

**Core data model:**
- RDF triples: subject-predicate-object (e.g., `dbr:Berlin dbo:populationTotal "3748148"`)
- DBpedia Ontology: 768 classes in a DAG hierarchy, 3,000+ properties
- Entities are URIs, interlinked with other Linked Open Data sources

**How it handles key concerns:**
- **Claims:** Each triple is a claim, but they are extracted *automatically* from Wikipedia, so quality is uneven.
- **Evidence/Provenance:** Triples link back to the Wikipedia article they were extracted from, but no statement-level provenance.
- **Confidence:** No confidence model. Extraction errors are common.
- **Versioning:** Follows Wikipedia revision history. Periodic data dumps.
- **Relationships:** Typed via the ontology, but shallow (infobox-derived, not deep semantics).

**What works well:**
- Massive scale through automation
- Good interoperability via RDF/SPARQL and links to other LOD datasets
- The ontology provides useful typing

**What's missing:**
- Extraction quality is a constant problem -- Wikipedia infoboxes are inconsistent
- No provenance below the page level
- Not suitable for scientific knowledge -- too shallow, too noisy

### 2c. Google Knowledge Graph

**What it is:** Google's proprietary knowledge graph powering search results, info panels, and entity disambiguation.

**Core data model:**
- Entities with types drawn from schema.org vocabulary
- Search API returns: `name`, `description`, `image`, `detailedDescription`, `url`, entity type(s), and a `resultScore`
- Internally uses a massive entity-relationship graph, but the public API is severely limited

**Key limitations:**
- API returns *individual entities*, not graphs of relationships
- Maximum 500 results per query, default 20
- No way to traverse relationships, query subgraphs, or access the underlying structure
- Read-only; no contribution mechanism
- Schema.org types are too coarse for scientific knowledge

**What works well:**
- Excellent entity disambiguation and linking
- Schema.org typing provides broad interoperability

**What's missing:**
- Completely proprietary, closed system -- antithetical to open science
- No provenance, confidence, versioning, or relationship traversal via API
- Designed for consumer search, not knowledge management

### Key Lessons from Knowledge Graphs

1. **Statement-level metadata (Wikidata model) is excellent.** Claims with qualifiers, references, and ranks is a powerful pattern. Adopt this.
2. **Ranks (preferred/normal/deprecated) are better than deletion** for evolving knowledge.
3. **`somevalue`/`novalue` is an important pattern** -- explicitly representing uncertainty and absence.
4. **Community-governed ontologies evolve well** but need tooling to prevent fragmentation.
5. **Encyclopedic fact models break for science.** Scientific claims require richer context (experimental conditions, statistical significance, sample sizes, methodology) than simple property-value qualifiers support.

---

## 3. Block-Based Knowledge Systems: Roam Research, Obsidian, LogSeq

### Data Model Comparison

**Roam Research:**
- Built on Datomic (Clojure Datalog database)
- The **block** is the atomic unit (every bullet point is a database entity)
- Tree structure: pages contain blocks, blocks contain child blocks
- Relationships: `:block/parents`, `:block/children` (immediate descendants only)
- Every block has a unique ID, is individually referenceable and embeddable
- Bidirectional links via `[[wikilinks]]` automatically generate backlinks with context
- Block references via `((block-id))` allow transclusion
- Queryable via Datalog queries directly in the UI

**LogSeq:**
- Open source, stores data as local Markdown files (not a cloud database)
- Block-based like Roam -- everything is a bullet point, blocks are the primary unit
- Bidirectional links and block references similar to Roam
- Journal-first approach (daily pages as default entry point)
- Properties on blocks via `key:: value` syntax
- Graph visualization for navigating connections

**Obsidian:**
- Local-first, stores as plain Markdown files in folders
- The **document** (note/page) is the primary unit, not the block
- Blocks exist but are not first-class citizens -- block references (`^block-id`) are less elegant
- Bidirectional links via `[[wikilinks]]` with backlinks panel
- Powerful plugin ecosystem (Dataview for queries, Graph Analysis, etc.)
- No structured data model beyond Markdown + YAML frontmatter
- Canvas view for spatial arrangement of notes

### How They Handle Key Concerns

- **Claims:** Blocks can represent claims, but there is no semantic typing -- a claim looks the same as a todo item or a recipe ingredient. No structured assertion model.
- **Evidence:** Links between blocks provide associative connections, but there is no typed evidence relationship (e.g., "supports," "contradicts," "is-derived-from").
- **Provenance:** None in any meaningful sense. No source tracking, no attribution.
- **Confidence:** Not represented at all.
- **Versioning:** File-level via git (Obsidian, LogSeq) or cloud sync (Roam). No semantic versioning of individual claims.
- **Relationships:** Bidirectional links are powerful but untyped. A link between two blocks means "related" but says nothing about *how* they are related.

### What Works Well

- **Blocks as atoms** (Roam/LogSeq) are the right granularity. Individual thoughts, not pages, should be the unit.
- **Bidirectional links** make knowledge discovery emergent -- you don't have to know in advance how things connect.
- **Transclusion** (embedding blocks by reference) avoids duplication and keeps a single source of truth.
- **Low friction input** -- just type, nest, and link. The barrier to entry is extremely low.
- **Daily notes / journal-first** approach (LogSeq) provides natural chronological capture.
- **Local-first / plain files** (Obsidian, LogSeq) give users data ownership.

### What's Missing or Broken

- **No semantic typing.** All links are equal. You cannot distinguish "supports" from "contradicts" from "is-an-instance-of." This is the critical limitation for scientific knowledge.
- **Single-user by design.** These tools are personal knowledge management systems. Multi-user collaboration, attribution, and access control are afterthoughts or absent.
- **No shared ontology.** Each user's graph is idiosyncratic. My `[[thermodynamics]]` page has nothing to do with yours. There is no shared namespace or vocabulary.
- **No verification or trust.** Anyone can write anything in a block. No mechanism for peer review, formal verification, or trust networks.
- **No structured queries over semantics.** You can search for text and follow links, but you cannot ask "what claims about X are supported by evidence from randomized controlled trials?"
- **Scale ceiling.** These systems work for hundreds to low-thousands of notes. Scientific knowledge has millions of claims. Graph views become useless at scale.

### Lessons for Our Design

1. **Blocks/claims as atoms is correct.** The atomic unit should be a single assertion, not a document. Roam got this right.
2. **Bidirectional links are essential** but must be *typed*. Every relationship needs a semantic label.
3. **Low-friction input is non-negotiable.** If adding knowledge requires filling out a schema form, researchers will not use it. The system must accept messy input and structure it afterward (via AI or human curation).
4. **Transclusion / single-source-of-truth** prevents knowledge duplication. A claim should exist once and be referenced everywhere.
5. **Personal tools fail at shared knowledge.** The transition from personal notes to shared scientific knowledge requires: shared ontology, attribution, access control, and conflict resolution.

---

## 4. Open Research Knowledge Graph (ORKG)

**What it is:** A platform by TIB Hannover that aims to describe research papers in a structured, comparable manner. The most direct predecessor to what we are building.

### Core Data Model

ORKG uses an RDF-like triple structure with its own resource/predicate/literal system:

```
Paper (resource)
  ├── title, DOI, authors, publication date, venue (metadata)
  ├── research field (classification)
  └── Contributions (one or more per paper)
        └── Structured statements: Resource -[Predicate]-> Resource/Literal
```

**Key entity types:**
- **Resources** (R-ids): Entities in the graph (papers, contributions, concepts, methods)
- **Predicates** (P-ids): Named relationships between resources
- **Literals**: Concrete values (strings, numbers)
- **Classes**: Type classifications for resources

**Contributions** are the key unit -- a paper's distinct intellectual contributions, described via property-value statements.

**Comparisons** are ORKG's signature feature: side-by-side comparisons of contributions across papers addressing the same research problem. Properties are matched across contributions so you can compare, e.g., the "accuracy" of different transformer models.

**Templates** define expected structure for specific research problem types. E.g., a template for "transformer model evaluation" might require properties: `model family`, `parameter count`, `pretraining architecture`, `benchmark score`.

### How It Handles Key Concerns

- **Claims:** Partially. Contributions contain structured statements, but these are descriptive summaries of paper content, not formalized assertions with truth values.
- **Evidence:** Links back to source papers. No structured evidence chains.
- **Provenance:** Papers link to DOIs. Contribution descriptions trace to the original paper. User edit history is tracked.
- **Confidence:** Not represented. No verification status or confidence scores.
- **Versioning:** Resources can be updated, but no formal version history for individual statements.
- **Relationships:** User-defined predicates provide typed relationships, but the vocabulary is inconsistent across users and domains.

### What Works Well

- **Comparisons are killer.** Being able to compare structured contributions across papers is exactly what researchers need. This is ORKG's strongest innovation.
- **Templates for consistency.** Templates ensure that contributions in the same domain use the same properties, making them comparable.
- **User-contributed structure.** Researchers can describe their own papers in structured form, combining human domain expertise with structured data.
- **RDF compatibility** enables interoperability with the broader Linked Data ecosystem.

### What's Missing or Broken

- **Adoption is low.** Despite years of development, ORKG has limited content. The friction of manually structuring papers is too high, and the payoff is too uncertain.
- **Paper-centric, not claim-centric.** Like Semantic Scholar, the atomic unit is still the paper (or contribution), not individual claims.
- **No formal verification.** Structured descriptions are not verifiable assertions -- they are human-authored summaries that could be wrong.
- **Vocabulary fragmentation.** Without strict templates, different users describe the same concept differently. Predicate reuse is inconsistent.
- **Limited AI assistance.** Recent work uses LLMs for structured summarization, but AI integration is not deeply embedded in the workflow.
- **No disagreement model.** Comparisons show differences between contributions but do not model contradiction or conflict explicitly.

### Lessons for Our Design

1. **Comparisons are a must-have output.** The ability to compare structured claims across sources is among the highest-value features for researchers.
2. **Templates balance flexibility with consistency.** Adopt a template system for common research patterns, but allow freeform structure for novel work.
3. **Manual structuring does not scale.** ORKG's adoption problem proves that the input cost must be near zero. AI must do the heavy lifting, with humans reviewing/correcting.
4. **Vocabulary governance is critical.** Without it, the graph fragments into incomparable sub-islands.

---

## 5. Nanopublications

**What it is:** A paradigm for packaging the smallest publishable unit of scientific information -- a single assertion -- with full provenance and attribution, using RDF named graphs.

### Core Data Model

A nanopublication consists of four RDF named graphs:

```trig
# HEAD GRAPH -- structural metadata connecting the parts
:Head {
  : a np:Nanopublication .
  : np:hasAssertion :assertion .
  : np:hasProvenance :provenance .
  : np:hasPublicationInfo :pubinfo .
}

# ASSERTION GRAPH -- the actual claim (one or more RDF triples)
:assertion {
  ex:trastuzumab ex:is-indicated-for ex:breast-cancer .
}

# PROVENANCE GRAPH -- how the assertion was derived
:provenance {
  :assertion prov:wasDerivedFrom <http://example.org/experiment42> .
  :assertion prov:wasAttributedTo orcid:0000-0003-3934-0072 .
  :assertion dce:hasMethod "Western blot analysis" .
}

# PUBLICATION INFO GRAPH -- metadata about the nanopublication itself
:pubinfo {
  : dct:creator orcid:0000-0003-0183-6910 .
  : dct:created "2024-07-10T10:20:22.382+02:00"^^xsd:dateTime .
  : dct:license <http://creativecommons.org/licenses/by/4.0/> .
}
```

**Required well-formedness criteria:**
- Exactly one quad declaring the nanopublication type
- Exactly one assertion, provenance, and publication info graph per nanopublication
- Distinct URIs for all four graph identifiers
- Provenance graph MUST reference the assertion graph
- Publication info graph MUST reference the nanopublication URI

**Trusty URIs:** Cryptographic hashes appended to nanopublication URIs provide immutability verification -- if any triple changes, the hash no longer matches. This enables tamper-evident knowledge.

### How It Handles Key Concerns

- **Claims:** First-class. The assertion graph IS the claim. This is the correct granularity.
- **Evidence:** The provenance graph links assertions to their sources, methods, and derivation chains. Provenance-driven nanopublications can represent multi-source assertions with full lineage.
- **Provenance:** Two distinct layers: (1) assertion provenance (how the claim was derived), (2) publication info (who published the nanopublication and when). This separation is elegant.
- **Confidence:** Not built-in, but can be expressed via provenance triples (e.g., `prov:hadConfidenceLevel`). Recent extensions add trust networks.
- **Versioning:** Trusty URIs make nanopublications immutable. New versions are new nanopublications that supersede old ones. Version chains are explicit.
- **Relationships:** Assertions can contain any RDF triples, so arbitrary relationships are supported.

### What Works Well

- **The assertion/provenance/publication-info separation is elegant and correct.** This three-layer model cleanly separates what is claimed, how it was derived, and who published it. This is the right architecture.
- **Claim-level granularity.** Finally, the atomic unit is a single assertion, not a paper or section.
- **Trusty URIs** provide tamper-evidence and immutability -- important for scientific integrity.
- **Decentralized by design.** Nanopublications can be published by anyone, anywhere, and aggregated by search services. No central authority required.
- **RDF interoperability** links into the broader Linked Data ecosystem.

### What's Missing or Broken

- **RDF is hostile to humans.** Writing RDF triples, even in Turtle syntax, is painful. Researchers will not do this. The input barrier is enormous.
- **Adoption is very low** outside of specific biomedical communities (e.g., DisGeNET, neXtProt). The format is theoretically beautiful but practically unused.
- **No query interface for non-experts.** SPARQL is powerful but inaccessible to most researchers.
- **Ontology dependence.** Every assertion requires agreed-upon URIs for subjects, predicates, and objects. Ontology engineering is a bottleneck.
- **No support for complex arguments.** A single RDF triple can express "X causes Y" but cannot express "X causes Y under conditions Z, with effect size D, as measured by method M, in population P" without an explosion of triples and reification.
- **No built-in confidence or verification model.** Extensions exist but are not standard.

### Lessons for Our Design

1. **The three-layer model (assertion / provenance / metadata) is the right architecture.** Adopt this separation.
2. **Claim-level granularity is correct.** Do not compromise on this.
3. **Immutability + versioning via content-addressing** is the right approach for scientific integrity.
4. **RDF is the wrong surface syntax.** The model is right, but the format must be human-friendly (JSON, natural language with AI structuring, etc.).
5. **Decentralized publication** is appealing but premature for an MVP. Start centralized, design for future federation.

---

## 6. Research Object Crate (RO-Crate)

**What it is:** A community standard for packaging research data with structured metadata, based on Schema.org annotations in JSON-LD.

### Core Data Model

An RO-Crate is a directory containing:
1. Research data (files, datasets, code, etc.)
2. `ro-crate-metadata.json` -- a JSON-LD file describing the contents

```json
{
  "@context": "https://w3id.org/ro/crate/1.1/context",
  "@graph": [
    {
      "@id": "ro-crate-metadata.json",
      "@type": "CreativeWork",
      "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
      "about": {"@id": "./"}
    },
    {
      "@id": "./",
      "@type": "Dataset",
      "name": "My Research Dataset",
      "author": {"@id": "https://orcid.org/0000-0001-..."},
      "datePublished": "2024-06-15",
      "hasPart": [
        {"@id": "data.csv"},
        {"@id": "analysis.py"},
        {"@id": "workflow.cwl"}
      ]
    },
    {
      "@id": "data.csv",
      "@type": "File",
      "name": "Experimental results",
      "encodingFormat": "text/csv"
    }
  ]
}
```

**Key structural elements:**
- **Root Data Entity** (`./`): The dataset as a whole
- **Data Entities**: Files and folders in the crate
- **Contextual Entities**: People, organizations, instruments, software, etc. providing provenance
- **Profiles**: Domain-specific extensions (Workflow RO-Crate, Process Run Crate, etc.)

The `@graph` is a flat array of cross-referenced entities using `@id` URIs.

### How It Handles Key Concerns

- **Claims:** Not applicable. RO-Crate packages *artifacts*, not assertions. It describes what files exist and their metadata, not what claims they contain.
- **Evidence:** Artifacts (data files, code, results) ARE the evidence, packaged with metadata about how they were produced.
- **Provenance:** Rich provenance via contextual entities -- who created the data, with what instruments, using what software, funded by whom.
- **Confidence:** Not represented.
- **Versioning:** Via `version` property on the dataset. Individual file versioning depends on external systems.
- **Relationships:** Schema.org properties provide typed relationships between entities.

### What Works Well

- **JSON-LD is human-readable** (compared to RDF/XML or Turtle). The format is approachable.
- **Schema.org base vocabulary** provides broad interoperability without specialized ontology knowledge.
- **Profiles** allow domain-specific extensions without changing the core format.
- **Packaging data with metadata** in a single directory is practical and portable.
- **Flat entity graph** with cross-references is a clean data model.

### What's Missing or Broken

- **Metadata about artifacts, not knowledge.** RO-Crate describes "this CSV file was created by researcher X on date Y" but not "the data in this CSV supports claim Z."
- **No semantic content model.** The schema describes the *container*, not the *contents*.
- **Primarily for archival/publication**, not for active querying or reasoning.

### Lessons for Our Design

1. **JSON-LD with Schema.org base** is a good format choice -- approachable, extensible, and interoperable.
2. **Flat entity graphs with `@id` cross-references** are a clean data model pattern.
3. **Profiles/extensions** are the right way to handle domain-specific structure without bloating the core.
4. **Artifact packaging is complementary** to knowledge structuring. Our system should be able to *reference* RO-Crate packaged data as evidence for claims.

---

## 7. Lean / Mathlib

**What it is:** Lean 4 is a dependently-typed functional programming language and interactive theorem prover. Mathlib is its community-driven library of formalized mathematics (~2M lines), one of the largest formal mathematical knowledge bases.

### Core Data Model

Lean's knowledge structure is fundamentally different from all other systems discussed here: **knowledge is code, and correctness is compiler-enforced.**

**Declaration types:**

| Declaration | Purpose | Example |
|------------|---------|---------|
| `theorem` | Mathematical statement with proof | `theorem add_comm : a + b = b + a := ...` |
| `lemma` | Minor theorem (functionally identical) | `lemma helper : ...` |
| `def` | Function or value definition | `def square (n : Nat) : Nat := n * n` |
| `structure` | Bundled data with named fields | `structure Point where x : Float; y : Float` |
| `class` | Typeclass (algebraic structure) | `class Group (G : Type) where ...` |
| `inductive` | Inductive type definition | `inductive Bool where \| true \| false` |
| `axiom` | Unproven assumption | `axiom choice : ...` |

**Dependency structure:**
- Modules (`.lean` files) import other modules
- Imports create a DAG of dependencies
- Public vs private scope controls visibility
- Namespaces organize declarations hierarchically (e.g., `Nat.add_comm`)

**The proof paradigm:**
- Theorems are *types* (propositions)
- Proofs are *terms* inhabiting those types
- The type checker verifies proofs automatically -- if it compiles, it is correct
- Tactic mode provides high-level proof strategies; term mode provides direct proof construction

**Mathlib structure:**
- Organized into a hierarchy: `Mathlib.Algebra.Group.Defs`, `Mathlib.Topology.Basic`, etc.
- ~200K+ theorems and definitions
- Extensive use of typeclasses for algebraic abstraction (groups, rings, fields, topological spaces, etc.)
- Searchable via name patterns, type signatures, or the `exact?`/`apply?` tactics

### How It Handles Key Concerns

- **Claims:** Every `theorem` and `lemma` is a precise, machine-verifiable claim. The claim IS its type signature.
- **Evidence:** Every theorem's proof IS the evidence. If the proof compiles, the claim is verified. No ambiguity.
- **Provenance:** Imports create an explicit dependency DAG. Every theorem's proof shows exactly which prior results it depends on.
- **Confidence:** Binary: either the proof type-checks (verified) or it does not. No probabilistic confidence -- but `sorry` marks unproven claims, and `axiom` marks assumptions.
- **Versioning:** Via git, with CI ensuring all proofs still compile after changes. Breaking changes are caught automatically.
- **Relationships:** The type system encodes rich mathematical relationships. Typeclasses represent "is-a" hierarchies (every field is a ring, every ring is a group, etc.).

### What Works Well

- **Machine verification is the gold standard.** If the proof compiles, the claim is true (modulo axioms). No other system offers this guarantee.
- **Explicit dependency DAG.** You can trace exactly what any theorem depends on.
- **Composability.** New theorems build on existing ones in a type-safe way. Knowledge compounds.
- **`sorry` and `axiom` make assumptions explicit.** You always know what is proven vs. assumed.
- **Community governance** (PR review, CI) ensures quality without central authority.

### What's Missing or Broken

- **Only works for mathematics** (and to some extent, verified software). Empirical science -- biology, chemistry, social science -- cannot be expressed in dependent types. You cannot prove "aspirin reduces headache risk" in Lean.
- **Extremely high barrier to entry.** Formalizing even simple math takes years of training. This is inaccessible to most scientists.
- **No uncertainty model.** Real science deals in probabilities, effect sizes, and confidence intervals. Lean's binary proved/not-proved does not capture this.
- **No natural language interface.** Lean code is precise but opaque to non-experts.
- **No metadata beyond the proof.** Who formalized it, when, what real-world paper it corresponds to -- this is tracked in git/PRs, not in the formal system itself.

### Lessons for Our Design

1. **Explicit dependency DAGs are essential.** Every claim should declare what it depends on. This is how you get composable, auditable knowledge.
2. **Verification status should be first-class.** Borrow the `sorry` pattern: claims can exist in an unverified state, but this state is visible and queryable.
3. **Typeclasses / algebraic structure** is the right way to handle "is-a" hierarchies for mathematical objects.
4. **Binary verification does not generalize to empirical science.** We need a richer confidence model: verified (formally proven), strongly supported (multiple RCTs), weakly supported (single observational study), contested (conflicting evidence), retracted, etc.
5. **The compilation metaphor is powerful.** "If the knowledge base compiles, all dependencies are satisfied and all proofs check out" is an aspirational property. Even partial type-checking (e.g., ensuring claimed dependencies actually exist) adds value.

---

## 8. Schema.org / Dublin Core

### 8a. Schema.org

**What it is:** A collaborative vocabulary (founded by Google, Microsoft, Yahoo, Yandex) for structured data on the web. Used by millions of websites for SEO and machine-readable metadata.

**Relevant types for scholarly works:**

`ScholarlyArticle` (subtype of `Article` > `CreativeWork` > `Thing`)

**Key properties (inherited from CreativeWork):**

| Property | Type | Purpose |
|----------|------|---------|
| `name` / `headline` | Text | Title |
| `author` | Person/Organization | Author(s) |
| `datePublished` | Date | Publication date |
| `abstract` | Text | Abstract |
| `citation` | CreativeWork/Text | References |
| `about` | Thing | Topic/subject |
| `isPartOf` | CreativeWork | Parent publication |
| `keywords` | Text/DefinedTerm | Keywords |
| `license` | URL/CreativeWork | License |
| `funder` / `funding` | Organization/Grant | Funding info |
| `version` | Number/Text | Version |
| `interpretedAsClaim` | Claim | Claims made in the work |
| `isBasedOn` | CreativeWork/URL | Prior work |
| `correction` | CorrectionComment | Corrections/errata |

Notable: Schema.org does have a `Claim` type and an `interpretedAsClaim` property, indicating awareness that creative works contain claims. However, this is rarely used in practice.

**Additional types:** `Dataset`, `SoftwareSourceCode`, `Review`, `Comment`, `MediaObject` -- Schema.org covers the full range of research artifacts.

### 8b. Dublin Core

**What it is:** One of the oldest and most widely adopted metadata standards (1995). ISO 15836. Fifteen core elements for describing any resource.

**The 15 core elements:**

| Element | Description |
|---------|-------------|
| `Title` | Name of the resource |
| `Creator` | Entity primarily responsible for the content |
| `Subject` | Topic of the content |
| `Description` | Abstract or summary |
| `Publisher` | Entity responsible for making the resource available |
| `Contributor` | Entity responsible for contributions |
| `Date` | Date of an event in the lifecycle |
| `Type` | Nature or genre of the content |
| `Format` | Physical or digital manifestation |
| `Identifier` | Unambiguous reference (DOI, ISBN, etc.) |
| `Source` | Related resource from which this is derived |
| `Language` | Language of the content |
| `Relation` | Related resource |
| `Coverage` | Spatial or temporal scope |
| `Rights` | Legal rights information |

Qualified Dublin Core adds refinements: `created`, `issued`, `modified` refine `Date`; `abstract` refines `Description`; `isPartOf`, `hasPart`, `isReferencedBy`, `references` refine `Relation`.

The Scholarly Resources Application Profile (SRAP) extends Dublin Core for academic works, adding properties like `degreeGrantor`, `opponent`, `supervisor` for theses.

### How They Handle Key Concerns

- **Claims:** Schema.org has a `Claim` type and `interpretedAsClaim`, but these are metadata *about* web content for fact-checking, not a knowledge representation system. Dublin Core has no claim concept.
- **Evidence:** Neither provides an evidence model.
- **Provenance:** Dublin Core's `Source`, `Creator`, `Date` provide basic provenance. Schema.org's `isBasedOn`, `author`, `datePublished` similarly.
- **Confidence:** Not represented in either.
- **Versioning:** Schema.org's `version` property. Dublin Core's `modified` date qualifier. Basic.
- **Relationships:** Dublin Core's `Relation` refinements (`isPartOf`, `hasPart`, `references`, etc.) and Schema.org's richer property set provide typed relationships.

### What Works Well

- **Ubiquity.** These standards are everywhere. Any system that ignores them sacrifices interoperability.
- **Simplicity.** Dublin Core's 15 elements are learnable in minutes. Schema.org's JSON-LD is readable by developers.
- **Extensibility.** Both allow custom extensions while maintaining a common core.
- **Tooling.** Validators, generators, search engine support (Schema.org), library catalog integration (Dublin Core).

### What's Missing or Broken

- **Document-level metadata only.** These standards describe *documents*, not the knowledge within them. "This paper was published on X by Y" tells you nothing about what the paper claims.
- **No semantic depth.** `subject: "machine learning"` is a keyword, not a knowledge representation.
- **No relationships between claims.** You can say paper A `references` paper B, but not that claim 1 in paper A contradicts claim 7 in paper B.

### Lessons for Our Design

1. **Use Schema.org as the base vocabulary** for metadata (as RO-Crate does). Do not reinvent standard metadata.
2. **Dublin Core compatibility** ensures library/archive interoperability. Map our metadata to DC terms.
3. **The `interpretedAsClaim` property shows Schema.org already anticipates claim extraction** from documents. Build on this.
4. **These standards define the metadata layer, not the knowledge layer.** We need both: Schema.org for "who published what when" and a richer model for "what was claimed, with what evidence, at what confidence."

---

## Key Lessons for Knowledge Backend: Synthesis

### The Right Atomic Unit is a Claim

Every paper-centric system (Semantic Scholar, ORKG, Dublin Core) hits the same wall: papers bundle many claims into opaque documents. Nanopublications and Lean get the granularity right -- the atom is a single assertion/theorem. **Our atomic unit must be a claim (assertion), not a paper or document.**

### The Three-Layer Architecture is Correct

Nanopublications' separation of **assertion / provenance / publication metadata** is the right architecture. Every claim in our system should carry:
1. **The assertion itself** -- what is being claimed
2. **Provenance** -- how the claim was derived (evidence, methodology, sources)
3. **Metadata** -- who published it, when, under what license, etc.

### Typed Relationships are Non-Negotiable

Block-based tools (Roam, Obsidian) prove that bidirectional links are powerful, but their *untyped* links cannot distinguish "supports" from "contradicts" from "assumes." Wikidata's property system and Lean's dependency types show how typed relationships should work. **Every relationship must have a semantic type.**

### Confidence is a Spectrum, Not a Binary

Lean offers binary verification (proven/not-proven). Wikidata offers three ranks (preferred/normal/deprecated). Neither is sufficient for empirical science. **We need a richer confidence model:**
- Formally verified (machine-checked proof)
- Strongly supported (multiple independent replications, meta-analyses)
- Supported (peer-reviewed evidence)
- Weakly supported (preliminary results, preprints)
- Contested (conflicting evidence exists)
- Deprecated/Retracted

### Explicit Dependencies Form a DAG

Lean's import system and Mathlib's theorem dependencies show that knowledge composes when dependencies are explicit. **Every claim should declare what it assumes/depends on**, forming a directed acyclic graph. This enables: impact analysis (what breaks if this claim is retracted?), verification chains, and knowledge compilation.

### Input Friction Kills Adoption

ORKG's low adoption proves that manual structuring does not scale. Nanopublications' RDF syntax is hostile to humans. **The input surface must be low-friction:**
- Accept natural language, voice, images, PDFs
- Use AI to propose structure (claims, relationships, evidence)
- Humans review and correct, not create from scratch
- Structure emerges from use, not from upfront schema compliance

### Vocabulary Governance Prevents Fragmentation

ORKG's inconsistent predicates and Wikidata's qualifier sprawl show that uncontrolled vocabularies fragment knowledge. **We need:**
- A core vocabulary of relationship types (supports, contradicts, assumes, derived-from, instance-of, etc.)
- Templates for common research patterns (as ORKG does)
- AI-assisted vocabulary alignment (detecting when two predicates mean the same thing)
- Community governance for ontology evolution

### Comparisons are a Killer Feature

ORKG's comparison tables -- showing structured claims side-by-side across papers -- are among the highest-value outputs for researchers. **Design the schema so cross-claim comparison is a natural query**, not a special feature.

### Versioning Through Immutability

Nanopublications' trusty URIs and Lean's compilation model show the right pattern: **knowledge artifacts are immutable; new versions are new entities that explicitly supersede old ones.** This preserves history, enables tamper-evidence, and simplifies caching.

### Standards for Interoperability

Use Schema.org for document metadata (as RO-Crate does). Map to Dublin Core for library systems. Support DOI, ORCID, ArXiv IDs for external linking. Use PROV-O vocabulary for provenance. **Do not reinvent what already has a standard.**

### The Format Must Be Human-Friendly

RDF/Turtle is powerful but hostile. JSON-LD (as used by RO-Crate and Schema.org) strikes the right balance: structured, extensible, and readable by developers. **JSON-LD should be the primary serialization format**, with RDF export available for Linked Data interoperability.

---

## Summary Table

| System | Atomic Unit | Claims? | Provenance? | Confidence? | Versioning? | Input Friction |
|--------|------------|---------|-------------|-------------|-------------|----------------|
| Semantic Scholar | Paper | No | Paper-level | No | External IDs | N/A (read-only) |
| Wikidata | Statement | Yes (fact-level) | References + edit history | Ranks (3 levels) | Edit history | Medium (forms) |
| DBpedia | Triple | Sort of (auto-extracted) | Page-level | No | Wikipedia revisions | N/A (auto) |
| Google KG | Entity | No | No | No | No | N/A (closed) |
| Roam/Obsidian/LogSeq | Block/Note | No (untyped) | No | No | File-level (git) | Very low |
| ORKG | Contribution | Partial (descriptive) | Paper-level | No | Basic | High (manual) |
| Nanopublications | Assertion | Yes | Full (two layers) | Extensible | Immutable + chains | Very high (RDF) |
| RO-Crate | Dataset/File | No | Rich (artifacts) | No | Basic | Medium (JSON-LD) |
| Lean/Mathlib | Theorem | Yes (verified) | Dependency DAG | Binary (proven/not) | Git + CI | Very high (formal) |
| Schema.org | Document | Has `Claim` type | Basic | No | `version` property | Low (JSON-LD) |
| Dublin Core | Document | No | Basic | No | Date qualifiers | Low |

---

*Research compiled 2026-02-08. This document informs the schema design for the Knowledge Backend project.*
