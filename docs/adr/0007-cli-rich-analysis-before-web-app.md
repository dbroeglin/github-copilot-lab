# 0007. Ship CLI (Rich) analysis first; defer the web explorer

- **Status:** Accepted
- **Date:** 2026-06-14

## Context

The longer-term vision is a web application to explore experiments, runs, session logs, and
aggregated data interactively. But the immediate need is a working tracer bullet: prove the
end-to-end pipeline and give a readable overview of a single session. A web app implies new,
heavyweight concerns — a server, a frontend stack, packaging, auth — that would slow the thin
slice and risk over-building before the data model has settled.

## Decision

We will deliver the session overview as a **CLI command (`analyze`) rendered with Rich** now,
and **defer the web explorer** as future work (documented as TBD in `docs/analysis.md`). To
keep that door open without paying for it yet, the analysis is already separated from rendering
(ADR-0006) and persisted as `analysis.json`, so a web layer can later consume the same model
and artifacts.

## Consequences

- Fast path to a usable, demoable result with no new runtime dependencies (Rich is already used).
- The data contract (`SessionAnalysis`, `analysis.json`, the `results/` tree) is exercised and
  stabilized before a web app is built on top of it.
- Interactive, cross-run visual exploration is not yet available from the CLI; the web app
  remains an explicit, deliberate follow-up rather than an accident of scope creep.
