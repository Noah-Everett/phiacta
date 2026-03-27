---
name: Files
slug: files
description: "How to use file attachments to make entries more valuable — proofs, code, data, and more"
---

# Files

Every entry is backed by a git repository. Beyond the content file (`.phiacta/content.md`), you can attach any files that support the entry: source code, proofs, data, figures, analysis scripts, notebooks, configuration files — anything that adds value.

**Files are a core part of what makes Phiacta entries citable and verifiable.** A theorem with a machine-checked proof attached is more trustworthy than one without. A benchmark result with the raw data and analysis script is reproducible. A method entry with a reference implementation is immediately useful.

## What to attach

Think about what would make this entry self-sufficient:

- **Proofs** — formal proofs (Lean, Coq, Isabelle), proof sketches, verification scripts
- **Code** — reference implementations, analysis scripts, benchmarks, simulations
- **Data** — raw results, benchmark outputs, measurements, datasets (keep sizes reasonable)
- **Figures** — plots, diagrams, visualizations that support the content
- **Notebooks** — Jupyter notebooks, Mathematica notebooks combining narrative and computation
- **Configuration** — model configs, hyperparameters, environment specs for reproducibility

## File paths

Use paths that make sense for the content. If you have one file, just put it at the root — no need for a directory:

```
proof.lean
benchmark.py
results.csv
```

If you have several related files, organize them:

```
src/model.py
src/train.py
data/results.csv
figures/loss-curve.png
```

A flat structure works well for a handful of files. Organize into directories when it helps clarity.

## The content file

The entry's main content lives at `.phiacta/content.md` (or `.tex` / `.txt`). This file is managed through the content writing tools. The identity file `.phiacta/entry.yaml` is immutable and cannot be modified through the API.

All other paths in the repository are yours to use for attachments.

## Referencing files in content

You can embed images and link to files from the entry's markdown content. See the [internal linking guide](/guides/linking-format) for the syntax.

## Files and entry planning

When planning a batch of entries (e.g., during paper ingestion), map files to entries upfront. A natural approach is to put each file with the entry it most directly supports — a proof with its theorem, benchmark code with its result, a reference implementation with its method. Organize however makes sense for your use case.
