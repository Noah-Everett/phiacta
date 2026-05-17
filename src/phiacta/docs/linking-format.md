---
name: Internal Linking
slug: linking-format
description: "How to link between entries, files, and images in markdown content"
---

# Internal Linking

This guide covers linking in markdown content files (`.phiacta/content.md`). LaTeX and plain text formats do not support inline links.

## Linking to other entries

Link to other Phiacta entries using the absolute path `/entries/{id}`:

```markdown
[descriptive text](/entries/uuid-here)
```

### Guidelines

- **Descriptive link text reads better.** For example, `[centroid condition](/entries/{id})` not `[{id}](/entries/{id})`.
- **Consider glossing on first use.** When referencing a concept that might be unfamiliar, briefly explaining it inline and linking to the entry helps readers orient themselves: "the [centroid condition](/entries/{id}) (each codepoint is the conditional mean of its cell)."
- **Later mentions can be just the link.** After the first gloss, `[centroid condition](/entries/{id})` alone is fine.
- **Sentences that work without the link are easier to read.** The link adds depth, but readers who don't click it will still follow along if the text is self-explanatory. Write "this follows from the product error decomposition" not "this follows from [this](/entries/{id})."

## Linking to files

Link to files in the same entry's repository using relative paths:

```markdown
[view the proof](proofs/theorem.lean)
[benchmark script](src/benchmark.py)
```

These open in the website's file viewer. Relative paths resolve to files in the current entry's repository.

## Embedding images

Display an image from the entry's repository with the `![]()` syntax:

```markdown
![description](figures/plot.png)
```

The path is relative to the repository root. The website resolves it automatically.

Hyphens instead of spaces in filenames can be more convenient in markdown:

```
figures/loss-curve.png        # conventional
figures/loss curve.png         # also works
```

## Linking within the same entry

To link to a heading inside the same entry, use a `#` anchor link:

```markdown
[Appendix A](#appendix-a-derivation)
[back to overview](#overview)
```

These resolve to a same-page scroll — the slug after `#` should match the auto-generated heading id (lowercase, hyphens for spaces).

## How linking works

- **Entry links** start with `/entries/` or `/users/` (absolute path with a UUID). These link to other pages on the platform.
- **File links and images** use relative paths (no leading `/`). These resolve to files in the current entry's repository.
- **Hash anchors** start with `#`. These scroll to a heading inside the current entry.

A relative path always means "a file in this entry's repo." An absolute `/entries/` path always means "another entry on the platform." A `#` prefix always means "a heading in this entry."
