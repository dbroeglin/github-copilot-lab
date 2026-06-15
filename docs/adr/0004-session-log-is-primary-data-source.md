# 0004. The Copilot session log is the primary data source

- **Status:** Accepted
- **Date:** 2026-06-14

## Context

To measure *what Copilot actually did* — turns taken, tools invoked, failures, tokens, wall-
clock time — we need a rich, structured trace, not just the process exit code or the final
stdout. The Copilot CLI already records one: a per-session `events.jsonl` under
`~/.copilot/session-state/<session-id>/`, an append-only stream of typed events
(`session.start`, `assistant.turn_start`, `assistant.message`, `tool.execution_start` /
`…_complete`, `assistant.turn_end`, `session.warning`, `hook.*`, …).

## Decision

We will make that **session log the primary data source**. We invoke Copilot with a generated
`--session-id` per trial, copy the resulting `events.jsonl` into the trial's result folder, and
derive everything downstream from it: flat `Metrics` for aggregation, and a richer
`SessionAnalysis` (timeline, tool histogram, token totals) for inspection. Parsing is defensive
and grounded in the observed real-world event schema, tolerating missing/extra fields and
unknown event types.

## Consequences

- We capture fidelity the exit code can't: per-turn behavior, which tool failed, token usage.
- We are coupled to an event schema we do not own. Parsers must degrade gracefully and be easy
  to update; correlation (e.g. `toolCallId` → tool name/success) lives in one place.
- The raw log is always retained, so re-analysis with improved parsers needs no re-run.
- Token accounting reflects what the log exposes today (output tokens per assistant message);
  fields that are absent are reported as unknown rather than guessed.
