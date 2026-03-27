---
name: Entry Lifecycle
slug: entry-lifecycle
description: "Status, archiving, edit proposals, and issues — how entries change over time"
---

# Entry Lifecycle

Entries are versioned and immutable in the git sense — every change is a commit. But they go through a lifecycle of status changes, edits, and discussion.

## Status

- **active** — The default state. The entry is visible, searchable, and citable.
- **archived** — Hidden from search and listings, but still accessible by ID. Use this to temporarily hide entries during batch operations (e.g., building a set of interconnected entries before making them all visible at once).

## Archiving pattern

When creating a group of related entries (e.g., ingesting a paper), a common pattern is:

1. Create the top-level entry and **archive** it immediately.
2. Create all component entries and wire references.
3. **Unarchive** the top-level entry once everything is connected.

This prevents users from seeing a half-built structure.

## Edit proposals

Edit proposals are the mechanism for suggesting changes to entries you don't own. They work like pull requests:

1. Create an edit proposal on an entry, describing the change.
2. The entry owner reviews and either merges or closes it.

Use edit proposals for corrections, improvements, or additions to existing entries.

## Issues

Issues are for flagging problems or starting discussion about an entry:

- Factual errors or inaccuracies
- Missing information or context
- Broken references or outdated content
- Suggestions for improvement

Issues are lighter-weight than edit proposals — they describe a problem without proposing a specific fix.
