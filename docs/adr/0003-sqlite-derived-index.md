# 0003. A derived SQLite index for cross-run queries

- **Status:** Superseded by ADR-0020
- **Date:** 2026-06-14

## Context

The filesystem is canonical (ADR-0002), but answering questions *across* runs — "success rate
per variant over the last month", "most expensive trials by tokens" — by walking directories
and parsing JSON is slow and awkward. We want ad-hoc analytical queries without a database
server or a heavy dependency.

## Decision

We will maintain a **SQLite index at `results/index.db`** with tables for experiments, runs,
variants, and trials. The runner updates it incrementally after each run, and a `reindex`
command drops and rebuilds it purely by scanning `results/`. The index is a cache, never a
source of truth.

## Consequences

- Cross-run analysis is a SQL query away; SQLite ships with Python (no new runtime dependency).
- The index can be deleted or corrupted with zero data loss — `reindex` restores it.
- Schema changes are cheap: bump the schema and reindex.
- Writers must keep the index in sync (or accept that `reindex` is occasionally required); the
  index is intentionally excluded from version control.
