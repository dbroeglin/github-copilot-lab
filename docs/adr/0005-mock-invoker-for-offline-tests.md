# 0005. A MockInvoker keeps the harness offline-testable

- **Status:** Accepted
- **Date:** 2026-06-14

## Context

Exercising the harness end to end touches the Copilot CLI, which needs authentication, network,
and credits, and is non-deterministic. That is unacceptable for unit tests and unfriendly for a
quick "does the pipeline work?" check. But the parts *around* the invocation — provisioning,
log capture, metrics, analysis, reporting, indexing — are exactly what we want to test cheaply.

## Decision

We will define an `Invoker` protocol with two implementations: `CopilotInvoker` (shells out to
the real CLI) and `MockInvoker` (simulates a run). The mock writes a small but **realistic,
multi-turn `events.jsonl` in the real event schema** — and may run an optional `solver`
callback to mutate the workspace as if Copilot completed the task. A `--dry-run` flag and the
entire test suite use the mock; no test requires real Copilot or network.

## Consequences

- The full pipeline (run → capture → metrics → analysis → report → index) is tested offline and
  deterministically; `--dry-run` is a faithful smoke test.
- Because the mock emits the real schema, dry-runs produce meaningful analyses, not toy data.
- The synthetic event generator must track the real schema as it evolves, or dry-run output
  drifts from reality (mitigated by ADR-0004's defensive parsing and retained raw logs).
