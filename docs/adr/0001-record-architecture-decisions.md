# 0001. Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-06-14

## Context

`copilot-experiments` is a research harness whose value depends on the *reasons* behind its
design as much as the code itself: why the filesystem is canonical, why runs are offline-
testable, how the session log is interpreted. Those reasons were previously implicit, living
in `AGENTS.md` invariants and commit messages, where they are hard to discover and easy to
erode. As we start the tracer-bullet work (a real experiment run plus session-log analysis),
we are making several fresh decisions worth capturing deliberately.

## Decision

We will keep an **Architecture Decision Record** log under `docs/adr/`, one short Markdown
file per significant decision, using the Nygard format (Context / Decision / Consequences).
We will record both the foundational decisions already embodied in the codebase and new ones
as they are made. ADRs are append-only; a decision is changed by superseding it with a new ADR.

## Consequences

- New contributors (and agents) can read the *why*, not just the *what*.
- Each significant change should consider whether it needs an ADR; this is a small ongoing cost.
- The `AGENTS.md` "architecture invariants" become a quick checklist that points at the ADRs
  for the full rationale.
