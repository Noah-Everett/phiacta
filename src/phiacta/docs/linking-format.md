---
name: Internal Linking Format
slug: linking-format
description: "How to link between entries in content using markdown: [text](/entries/{id})"
---

# Internal Linking Format

Use standard markdown links with the path `/entries/{id}`:

```markdown
[descriptive link text](/entries/uuid-here)
```

## Guidelines

- **Link text should be descriptive**, not the UUID. Write `[log-uniform quantizer](/entries/589e997b-...)` not `[589e997b-...](/entries/589e997b-...)`.
- **Gloss on first use.** The first time you link to an entry, include a brief inline explanation: "[NMSE](/entries/{id}) (normalized mean squared error — the fraction of signal power lost to quantization)."
- **Subsequent mentions can be shorter.** After the first gloss, just `[NMSE](/entries/{id})` is fine.
- **Links are not a substitute for context.** The sentence should be understandable even if the reader doesn't follow the link. The link provides depth, not essential meaning.
