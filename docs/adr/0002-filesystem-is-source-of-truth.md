# 0002. The filesystem is the source of truth

- **Status:** Accepted
- **Date:** 2026-06-14

## Context

A run produces many artifacts: the prompt, the copied session log, parsed metrics, the
workspace diff, verification output, and the final workspace. We need these to be durable,
diffable, inspectable with ordinary tools, and easy to archive or share — and we need a story
for "what if the database is lost or its schema changes".

## Decision

We will treat the **`results/` directory tree as the canonical store**. Every run writes a
self-describing folder (`results/<experiment>/<run-id>/…`) containing all of its artifacts as
plain files (JSON, JSONL, Markdown, diffs). Any index or database is derived from this tree
and can be rebuilt from it at any time.

## Consequences

- Results are portable and tool-agnostic: `cat`, `jq`, `git diff`, and a file browser all work.
- No migration risk for primary data; the on-disk layout (see `docs/results-format.md`) is the
  contract.
- The layout must stay stable and documented; readers depend on it.
- Derived stores (e.g. the SQLite index, ADR-0003) must never hold data that cannot be
  regenerated from the filesystem.
