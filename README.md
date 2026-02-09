# NewPublishing

A new standard for sharing scientific knowledge — replacing papers with a queryable knowledge backend.

## Vision

Papers are an outdated medium for sharing knowledge now that AI can synthesize, query, and reason over structured data. This project builds:

1. **A canonical backend** storing semantic knowledge (claims, proofs, evidence, relationships)
2. **Extensions** as the only interface — input (voice, photos, PDFs) and output (paper view, API, search)

## Design Documents

Start with [`docs/design/synthesis.md`](docs/design/synthesis.md) — it synthesizes the work from four specialized analyses:

- [`schema-proposal.md`](docs/design/schema-proposal.md) — Core data model design
- [`devils-advocate.md`](docs/design/devils-advocate.md) — Critical analysis and edge cases
- [`extension-design.md`](docs/design/extension-design.md) — Input/output extension patterns
- [`prior-art.md`](docs/design/prior-art.md) — Analysis of existing systems

## Core Principles

- **Schema-first**: The data model is 80% of the work
- **Claims as first-class entities**: Not paragraphs, atomic statements
- **Extensions as views**: Users never touch the backend directly
- **Provenance tracking**: Every piece of knowledge knows where it came from
- **Machine-readable**: AI can reason over the graph

## Status

Early design phase. Schema proposal complete, implementation not started.
