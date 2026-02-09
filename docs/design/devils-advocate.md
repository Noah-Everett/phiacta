# Devil's Advocate: Knowledge Backend Design Critique

This document exists to stress-test the knowledge backend design before we commit to building it. Every challenge here is something we must either solve, mitigate, or consciously accept as a limitation.

---

## 1. The Expressiveness-Simplicity Paradox

### The Problem
The CLAUDE.md demands a schema that is simultaneously "maximally general" and "human-writable." These requirements are in fundamental tension, and every knowledge representation project in history has had to pick a side.

- **If you go maximally general** (everything is a triple: subject-predicate-object, like RDF), you can represent anything, but no human will sit down and write `<http://example.org/claim/42> <http://example.org/rel/supports> <http://example.org/claim/17>`. The Semantic Web tried this and it never achieved meaningful human adoption.
- **If you use specific entity types** (Paper, Theorem, Experiment, Dataset), it's writable and intuitive, but every new knowledge domain requires schema changes. You'd need a "Theorem" type for math, a "ClinicalTrial" type for medicine, a "Benchmark" type for ML, and so on forever.

### An Example
A materials scientist discovers that a particular alloy behaves unexpectedly at high temperatures. This "claim" involves: a material composition, experimental conditions, a measurement, a comparison to predicted behavior, and a hypothesis for why. What schema type is this? It's not a theorem, not a clinical trial, not a benchmark. If you force it into a generic triple, you lose the structure. If you need a custom type, your schema isn't general.

### Severity: Major
This isn't a dealbreaker because there IS a middle ground, but finding it requires real design work, not hand-waving about being "maximally general."

### Suggested Mitigation
Use a **small fixed core** (Claim, Evidence, Relationship, Agent, Context) with a **typed property bag** for domain-specific metadata. The core schema handles structure and traversal; the property bag handles domain specifics without schema changes. This is roughly what Notion and Roam did for note-taking. The key insight is: the schema governs the *graph structure*, not the *content*. Content lives in typed blobs that the schema doesn't need to understand.

But be honest: this means the system cannot reason deeply over domain-specific structure without domain-specific extensions. "Maximally general" and "maximally machine-readable" cannot both be true for the same layer.

---

## 2. The Granularity Problem

### The Problem
"Claims are first-class entities" is the central design commitment, but there is no natural unit of a "claim." Granularity is not a property of knowledge; it's a property of the *use case*.

Consider a single sentence from a biology paper: "In our study of 50 patients over 6 months, we observed a statistically significant (p < 0.05) reduction in headache frequency when administered 500mg aspirin daily compared to placebo."

This contains at minimum:
1. A population claim (50 patients)
2. A duration claim (6 months)
3. A statistical significance claim (p < 0.05)
4. A dosage claim (500mg daily)
5. A comparative claim (vs. placebo)
6. An outcome claim (reduced headache frequency)
7. A causal claim (aspirin caused the reduction)

Should this be 1 claim or 7? If 1, you can't query "what dosages of aspirin have been studied?" If 7, you've created an explosion of tiny claims that are meaningless without each other, and no author will decompose their work this way.

### An Example
A mathematician publishes a proof with 15 lemmas leading to one theorem. Is the theorem 1 claim? 16 claims? What about the proof techniques used -- are those claims too? If Lemma 3 is later shown to have an error, you need enough granularity to invalidate just that lemma and its dependents, not the whole paper. But if you decompose everything up front, the authoring burden is enormous.

### Severity: Major
This is THE hardest UX problem in the whole system. Get this wrong and either (a) the system is too tedious for authors, so nobody contributes, or (b) the granularity is too coarse for meaningful queries, so nobody queries.

### Suggested Mitigation
**Lazy decomposition.** Store the original claim as authored (coarse-grained), but allow progressive decomposition over time -- by the author, by other researchers, or by AI. Make decomposition a first-class operation: "Claim X was decomposed into Claims X.1, X.2, X.3" with the original preserved. This means the graph starts sparse and gets denser as knowledge is refined, which matches how science actually works.

The cost: query results are only as good as the decomposition that's been done. Early on, most knowledge will be coarse and hard to query precisely.

---

## 3. The Provenance Explosion

### The Problem
If every piece of knowledge tracks its full provenance chain, the provenance graph grows faster than the knowledge graph itself. Worse, provenance chains are deeply nested and often circular.

### An Example
Paper A makes Claim 1, citing Papers B and C. Paper B's relevant claim cited Papers D, E, and F. Paper D cited Papers G, H, I, J. Following this tree to its roots means traversing the entire citation graph of science. For any non-trivial claim, the full provenance is effectively "all of human knowledge in this field."

Worse: circular provenance. Textbook T summarizes findings from Papers A-Z. New Paper AA cites Textbook T as background. Paper BB cites AA and independently cites Paper B (which T also summarized). The provenance is no longer a tree or even a DAG -- it's a general graph with cycles.

### Severity: Minor (if handled correctly)
This is a well-understood problem in database systems (transitive closure on graphs). It's not fatal, but the design must address it explicitly.

### Suggested Mitigation
**Bounded provenance.** Only store *direct* provenance (one hop). The system can compute transitive provenance on demand via graph traversal, but never materializes the full chain. For display purposes, show "direct sources" and "trace full provenance" as separate operations.

For cycles: allow them. Knowledge IS sometimes circular (theory motivates experiment which refines theory). Don't impose DAG constraints on the provenance graph; impose them only on *logical dependency* (Claim A logically depends on Claim B). Provenance ("where did this come from?") and logical dependency ("what does this assume?") are different relations and should be modeled separately.

---

## 4. Confidence Is Socially Constructed

### The Problem
The CLAUDE.md wants "confidence and verification status explicit." But confidence is not a number -- it's a complex social and epistemological phenomenon that resists quantification.

### An Example
Consider the claim "masks reduce COVID-19 transmission."
- In February 2020: low confidence (limited evidence)
- In March 2020: "high confidence" it was FALSE (WHO/CDC guidance: don't wear masks)
- In July 2020: moderate confidence it was TRUE (new studies)
- In 2021: high confidence TRUE (extensive evidence)
- In 2023: nuanced (depends on mask type, setting, variant)

Whose confidence? When? The same claim has wildly different confidence depending on who you ask, when you ask, and what evidence they've seen. A single confidence score is worse than useless -- it's actively misleading, because it projects false precision onto genuine uncertainty.

Different fields make this worse:
- Mathematics: a claim is either proven or not (binary, in principle)
- Physics: confidence comes from experimental replication and theoretical coherence
- Medicine: confidence comes from clinical trials with specific statistical thresholds
- Social science: confidence is contentious and standards are actively debated
- Engineering: "good enough to ship" is a valid confidence level

### Severity: Major
If you store a single confidence number, it will be gamed, misinterpreted, or ignored. If you don't store confidence at all, you lose a key design goal.

### Suggested Mitigation
**Don't store confidence as a property of a claim. Store it as a property of a *relationship between an agent and a claim*.**

Instead of `Claim.confidence = 0.85`, store `Agent X asserts Claim Y with confidence 0.85 given Evidence Z at Time T`. This means:
- Different agents can have different confidence
- Confidence is always relative to specific evidence
- Confidence has a timestamp
- "Community confidence" is computed (e.g., weighted average of agents' assessments), never stored as ground truth

This is more complex but honest. The alternative is building a system that lies about certainty.

---

## 5. The Versioning Nightmare

### The Problem
"Knowledge evolves, history preserved" interacts catastrophically with the dependency graph. If Claim A depends on Claim B, and B is updated, what happens to A?

### An Example
Claim B: "The speed of light in vacuum is 299,792,458 m/s."
Claim A: "At velocity v, time dilation is given by gamma = 1/sqrt(1 - v^2/c^2), where c = 299,792,458 m/s."

B is well-established, so this seems stable. But consider a more volatile domain:

Claim B: "The protein folding problem is NP-hard" (a specific complexity result).
Claim A: "Therefore, no polynomial-time algorithm can fold arbitrary proteins."
Claim C: "Therefore, our heuristic approach is the best we can do."

If Claim B gets a more precise version (e.g., "NP-hard for a specific formulation, but tractable for biologically relevant proteins"), then A needs revision, and C might be completely wrong.

Now scale this: one retracted paper might have been cited 500 times. Each of those 500 papers has their own downstream citations. Cascading invalidation could mark thousands of claims as "needs re-evaluation." This is computationally expensive and epistemologically fraught -- most of those downstream claims may still be valid via other evidence paths.

### Severity: Major
Naive versioning (propagate invalidation on any dependency change) makes the system unusable. No versioning makes it untrustworthy.

### Suggested Mitigation
**Distinguish between hard and soft dependencies.**
- **Hard dependency:** A is logically derived from B. If B changes, A MUST be re-evaluated. (e.g., a mathematical proof that uses a lemma)
- **Soft dependency:** A cites B for context/motivation, but A's validity doesn't depend on B. (e.g., "Building on the work of Smith et al.")

Only cascade invalidation through hard dependencies. For soft dependencies, flag but don't cascade.

For the unit of versioning: version individual claims, not the knowledge base. Use immutable claim versions (Claim B v1, Claim B v2) so that Claim A can pin to "B v1" and explicitly decide whether to upgrade. This is analogous to dependency pinning in package managers -- and for the same reasons.

---

## 6. Real-World Failure Modes

### 6a. Retraction Cascade

**Scenario:** A researcher retracts a paper containing Claim B. 200 other claims in the system have hard or soft dependencies on B.

**What breaks:** Do you mark all 200 as "suspect"? Many of them may be supported by independent evidence (not just B). Blanket invalidation creates noise. Selective invalidation requires understanding *why* each claim depends on B, which requires AI-level reasoning.

**Severity:** Major

**Mitigation:** On retraction, flag dependent claims for review but don't automatically invalidate. Provide tooling for researchers to re-assess: "Your claim depends on retracted Claim B. Is your claim still valid via other evidence?" This is a social process assisted by technology, not an automated one.

### 6b. Independent Discovery (Priority Disputes)

**Scenario:** Lab A and Lab B independently discover the same result. They both enter it into the system. Which is the canonical claim?

**What breaks:** If you merge them, who gets credit? If you keep both, you have duplicates that will confuse queries. If one was entered first, the system implicitly adjudicates a priority dispute, which is a deeply political problem in science.

**Severity:** Minor (but politically sensitive)

**Mitigation:** Allow duplicates. Model "same-as" relationships between claims explicitly. Let the community link them. Don't merge -- that destroys provenance. The system should surface "these claims appear to say the same thing" without choosing a winner.

### 6c. Context-Dependent Truth

**Scenario:** "Newtonian mechanics accurately describes the motion of objects" -- true for everyday objects, false for objects near the speed of light. "This drug is effective" -- true for population X, false for population Y.

**What breaks:** A claim stored without context is incomplete. But "context" is unbounded -- every claim is context-dependent if you look hard enough. Where do you draw the line?

**Severity:** Major

**Mitigation:** Make context/scope a required (but flexible) property of claims. "This claim holds under the following conditions: [...]". Use a controlled vocabulary for common scopes (domain, scale, population) but allow free-form for unusual ones. Accept that context will often be incomplete and allow refinement over time.

### 6d. Adversarial Inputs

**Scenario:** Someone adds "vaccines cause autism" to the system with fabricated evidence and inflated confidence.

**What breaks:** If the system treats all inputs equally, garbage enters the knowledge base. If it filters, who decides what's valid? You've re-invented peer review with all its problems.

**Severity:** Major (at scale)

**Mitigation:** Every claim is attributed to an agent. Trust is computed, not declared. New agents start with low trust. Community verification (upvotes/challenges) modulates effective confidence. This is messy and imperfect, but it's the same problem Wikipedia, Stack Overflow, and every other knowledge commons faces. Don't pretend to solve it; build infrastructure for managing it.

### 6e. Tacit and Procedural Knowledge

**Scenario:** A chemist knows that a reaction only works if you add the reagent slowly while stirring at a specific rate. This isn't a "claim" -- it's procedural know-how.

**What breaks:** The entire schema is oriented around propositional knowledge (claims that can be true or false). Procedural knowledge ("how to do X"), tacit knowledge ("the trick is to..."), and skill-based knowledge don't fit the claim-evidence model.

**Severity:** Minor (for v1)

**Mitigation:** Acknowledge this as out of scope for v1. Procedural knowledge can be represented as text blobs attached to relevant claims, but won't be first-class. This is fine -- papers don't handle tacit knowledge well either. Revisit in v2 if the system succeeds.

---

## 7. Scale and Performance

### The Problem
The system envisions graph traversal (dependency chains, provenance traces) combined with vector search (semantic similarity). Both are expensive at scale, and combining them is a largely unsolved performance problem.

### An Example
Query: "Find all claims related to protein folding that depend on experimental data from after 2020 and have confidence > 0.8 from at least 3 independent groups."

This requires:
1. Vector search for "protein folding" semantics
2. Graph traversal to find evidence dependencies
3. Filtering by date on evidence nodes
4. Aggregation of confidence across multiple agents
5. Counting distinct groups

At 10M claims with average 5 relationships each (50M edges), this query hits vector index, graph traversal, and aggregation. Each individually is feasible; combined, latency compounds. At 1B claims, this is a serious distributed systems problem.

### Severity: Minor (for now)
You won't have 1B claims for years. Premature optimization is the root of all evil. But the schema should not make future scaling impossible.

### Suggested Mitigation
Start with PostgreSQL + pgvector. This handles the first million claims easily. Design the schema so that graph traversal is bounded (e.g., max depth for dependency queries, pagination for results). If you reach scaling limits, migration to a dedicated graph database is a known, solved problem.

Do NOT start with Neo4j or a distributed graph database. The operational complexity is not justified until you have a scaling problem to solve.

---

## 8. Social and Incentive Problems

### The Problem
Even a perfect schema is useless if no one contributes. Researchers currently write papers because they must (for tenure, grants, prestige). The knowledge backend needs to either integrate with or replace these incentive structures.

### An Example
A tenure-track professor has limited time. She can either (a) write a traditional paper and submit to a journal, which counts toward tenure, or (b) decompose her knowledge into structured claims in this system, which counts toward nothing. She will choose (a) every time, regardless of how good the system is.

### Severity: Dealbreaker (long-term)
The best technology loses to misaligned incentives. If contribution to this system doesn't advance careers, it won't get contributions.

### Suggested Mitigation
Three strategies (not mutually exclusive):

1. **Parasitic adoption:** Don't ask researchers to change behavior. Build input extensions that ingest existing papers and decompose them. The system grows even if no one actively contributes. Researchers benefit from the query side without paying an authoring cost.

2. **Complement, don't replace:** Position the system as a tool that helps researchers write better papers, not as a replacement for papers. "Use our system to organize your knowledge, then export to paper format." Contribution is a side effect, not the goal.

3. **Long game on incentives:** Work with forward-thinking institutions and funders who are willing to accept structured knowledge contributions alongside traditional publications. This is a 10-year play.

Strategy 1 is the only one that works for v1. Be very honest about this: the system's initial knowledge will come from AI-processed papers, not from direct researcher contributions.

---

## 9. What Existing Systems Got Wrong

### The Semantic Web
**What happened:** RDF, OWL, SPARQL promised a machine-readable web of knowledge. Technically sound, but:
- Authoring was brutally hard (writing XML-based triples)
- No killer application for consumers
- No incentive to publish structured data vs. regular web pages
- Ontology alignment between independent publishers never worked

**Lesson for us:** The authoring experience is everything. If it's harder than writing prose, it will fail. Extensions that convert natural input (voice, photos, PDFs) into structured knowledge are not nice-to-haves; they're existential requirements.

### Google Knowledge Graph
**What happened:** Succeeded by being proprietary, curated, and focused on a narrow use case (search card enrichment). Not open, not researcher-facing, not designed for uncertainty or provenance.

**Lesson for us:** A focused, opinionated system beats a maximally general one. Don't try to represent all knowledge; start with one domain and do it excellently.

### Wikidata
**What happened:** Actually quite successful! But limited to encyclopedic facts, not scientific claims. Doesn't handle uncertainty, evidence, or provenance well. Contribution requires learning a specialized interface.

**Lesson for us:** Wikidata's success came from (a) integration with Wikipedia (massive distribution), (b) bot-friendly APIs (automated contributions), and (c) a community of dedicated volunteers. We need equivalents of all three.

### Academic Knowledge Graphs (Semantic Scholar, OpenAlex, etc.)
**What happened:** Good for metadata (who published what, citation counts) but don't capture the actual knowledge content of papers. They're bibliographic databases, not knowledge bases.

**Lesson for us:** Ingesting paper metadata is the easy part. Extracting actual claims and evidence from papers is the hard part, and it requires AI that doesn't exist reliably yet.

---

## The Three Hardest Problems

These are the challenges most likely to kill this project, in order of severity:

### 1. The Authoring Problem (Dealbreaker Risk)
No one will manually decompose their knowledge into structured claims. The system lives or dies on the quality of its input extensions -- especially AI-powered paper ingestion. If the AI can't reliably extract claims, evidence, and relationships from papers, the knowledge base will be empty or full of garbage. This is not a schema problem; it's an AI capability problem, and it depends on technology that is good-but-not-great in 2026.

**What to do:** Build the paper ingestion extension first. If it doesn't work well enough, stop and wait for AI to improve. Don't build a beautiful schema for an empty database.

### 2. The Granularity-Consistency Problem (Major Risk)
Without consistent granularity, the knowledge graph becomes a mess of claims at wildly different levels of abstraction. "E = mc^2" lives next to "Patient 47 showed improvement on day 12." Queries return incoherent mixtures. The graph is technically correct but practically useless.

**What to do:** Define granularity guidelines per knowledge domain. Build AI tools that suggest decomposition. Accept that granularity will be inconsistent and build query interfaces that handle this gracefully (e.g., "show me claims at this level of abstraction").

### 3. The Incentive Problem (Dealbreaker Risk, Long-Term)
Even with great technology, the system needs contributors. Academic incentives are deeply entrenched and changing them requires institutional buy-in that a software project cannot achieve on its own.

**What to do:** Don't try to change incentives in v1. Build a system that provides value to researchers as consumers (better search, better synthesis, better discovery) and grows its knowledge base via automated ingestion. Only after demonstrating clear value should you attempt to attract active contributors.

---

## Final Note

This critique is not an argument against building the system. It's an argument for building it with eyes open. The design in CLAUDE.md is ambitious and directionally correct, but it glosses over hard problems with phrases like "maximally general" and "confidence explicit." The hardest work is not the schema -- it's the AI that populates the schema, the UX that lets humans interact with it, and the social dynamics that make it sustainable.

Build the paper ingestion extension first. If that works, everything else follows. If it doesn't, nothing else matters.
