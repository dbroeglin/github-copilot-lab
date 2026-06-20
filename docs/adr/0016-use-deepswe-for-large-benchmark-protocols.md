# 0016. Use DeepSWE for large benchmark protocols

- **Status:** Accepted
- **Date:** 2026-06-19
- **Deciders:** project owner, Copilot

## Context

The Pier refactor made this package a thinner integration layer around Pier: author tasks and jobs,
run agents through Pier, and preserve native GitHub Copilot CLI session capture for analysis. The
previous SWE-bench module pulled the package back toward being a benchmark harness: dataset loading,
prediction export, Docker grading, write-back semantics, optional dependencies, example fixtures,
and CLI commands.

That is no longer the desired direction. DeepSWE is closer to the large benchmark protocol we want
to learn from or reuse. Keeping a parallel SWE-bench implementation here would duplicate benchmark
orchestration logic, add dependencies that are irrelevant to Copilot session capture, and make the
Pier integration less simple.

## Decision

We will remove in-tree SWE-bench support from `copilot-experiments`.

- No `swebench.py` module, `swebench-init`, `swebench-eval`, SWE-bench example, SWE-bench docs, or
  `swebench`/`datasets` optional dependency.
- No SWE-bench-specific fields in the public legacy `Task`/result models.
- No benchmark-specific difficulty-vs-cost reporting in the core summary path.
- DeepSWE is the preferred place for large SWE-style benchmark protocols and official grading
  workflows.
- This project remains focused on Pier task/job authoring, the local `copilot-cli` Pier installed
  agent, native Copilot CLI session capture, and reusable analysis/indexing of those sessions.

## Consequences

- The codebase is smaller and the main abstraction boundary is clearer: Pier runs tasks; this
  package captures and analyzes Copilot CLI behavior.
- Users who want SWE-style benchmark scale should use DeepSWE or contribute Copilot CLI support
  upstream there/Pier instead of expecting this package to own the benchmark runner.
- Existing historical ADR-0014 remains as a record of the previous direction but is superseded.
- Future benchmark-specific reporting should not be added here unless it can be expressed as a
  generic Pier job/session analysis feature.
