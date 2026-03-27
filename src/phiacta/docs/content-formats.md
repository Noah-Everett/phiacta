---
name: Content Formats
slug: content-formats
description: "Markdown, LaTeX, and plain text — when to use each format and how they work"
---

# Content Formats

Every entry has a content format that determines how its content is stored and rendered. Set it via the `content_format` field when creating an entry. The default is `markdown`.

## Markdown

The default and most common format. Supports standard markdown: headings, lists, tables, code blocks, links, images. Math is supported via `$...$` for inline and `$$...$$` for display blocks.

**Use markdown when:** the entry is mostly prose with some math, code, or structured content mixed in. This covers most entries — definitions, results, methods, notes, comparisons.

```markdown
The error bound is $\varepsilon^2/12 + O(\varepsilon^4)$, which for $N = 256$ gives:

$$\text{NMSE}^* = \frac{(R \ln 2)^2}{12 N^2} \approx 1.564 \times 10^{-4}$$
```

Markdown content also supports linking to other entries, embedding images, and linking to files in the entry's repository. See the [internal linking guide](/guides/linking-format) for details.

## LaTeX

Full LaTeX source. Use this when the entry is primarily mathematical — heavy notation, multi-line derivations, aligned equations, theorem environments.

**Use LaTeX when:** markdown's math support isn't enough. Long proofs, papers with custom macros, entries where the structure is driven by equations rather than prose.

```latex
\begin{theorem}
Among all $N$-level quantizers on $[a,b]$, the log-uniform quantizer
uniquely minimizes the worst-case NMSE over all densities.
\end{theorem}

\begin{proof}
By the equalization property, $\text{NMSE} = \varepsilon^2/12$
for any density $f$. For any non-log-uniform quantizer...
\end{proof}
```

Note: LaTeX content is the raw source. Rendering depends on the client — the website renders it, the API returns the source.

## Plain text

No formatting. The content is displayed as-is.

**Use plain text when:** the entry is a short note, a raw data dump, or content where formatting would add no value.

## Choosing a format

| Content is mostly... | Use |
|---------------------|-----|
| Prose with some math or code | `markdown` |
| Heavy math, proofs, derivations | `latex` |
| Raw text, notes, data | `plain` |

When in doubt, markdown is a safe default — it handles a wide range of content and is well-supported across tools.
