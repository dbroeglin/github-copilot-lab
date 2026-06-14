# 0006. Separate analysis data from its rendering

- **Status:** Accepted
- **Date:** 2026-06-14

## Context

We want a "good overview of what happened" in a session. Today that overview is rendered in the
terminal with Rich; tomorrow we expect a web explorer (ADR-0007) to present the same
information. If the logic that *computes* the overview is entangled with terminal-formatting
code, the web app would have to re-implement it, and the computation would be hard to test.

## Decision

We will split the concern in two:

- `analysis.py` turns a list of events into a **plain pydantic `SessionAnalysis`** (header,
  totals, per-turn timeline, tool histogram, warnings) — data only, no formatting.
- `render.py` takes a `SessionAnalysis` and renders it with **Rich**.

The runner also persists the analysis as `analysis.json` next to `metrics.json`, so the
structured overview is a first-class, serialized artifact.

## Consequences

- The analysis is unit-testable without touching a terminal, and is reusable by the CLI, the
  stored `analysis.json`, and any future web/HTTP layer — all consuming the same model.
- Adding a renderer (HTML, JSON-for-API) means writing a new presenter, not re-deriving data.
- A small amount of indirection (two modules instead of one) is the price.
