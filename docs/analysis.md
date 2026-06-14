# Session-log analysis

After a trial runs, the harness keeps the Copilot CLI **session log** (`events.jsonl`) and
derives two things from it:

- **`metrics.json`** — a few flat counters used for aggregation and the SQLite index.
- **`analysis.json`** — a richer, structured overview of *what happened* in the session.

This page covers the second one and the `analyze` command that renders it.

> Why a session log at all, and why split data from rendering? See
> [ADR-0004](adr/0004-session-log-is-primary-data-source.md) and
> [ADR-0006](adr/0006-separate-analysis-data-from-rendering.md).

## The `analyze` command

```bash
# Most recent run (first variant + first trial by default)
uv run copilot-experiments analyze --last

# A specific run / variant / trial
uv run copilot-experiments analyze 20260614T1419 --variant default --trial 1

# Any events.jsonl on disk — a stored trial log, or a live session under
# ~/.copilot/session-state/<id>/events.jsonl
uv run copilot-experiments analyze --file path/to/events.jsonl

# Long sessions: cap the timeline table
uv run copilot-experiments analyze --last --max-turns 15
```

The rendering (built with [Rich](https://rich.readthedocs.io/)) has four parts:

1. **Header** — session id, model(s), reasoning effort, repo/branch, Copilot version, start
   time, and wall-clock duration.
2. **Totals** — turns, user/assistant messages, tool calls, tool failures, warnings, hooks,
   tokens, and total event count.
3. **Tool usage** — a histogram of how often each tool was invoked and how often it failed.
4. **Timeline** — one row per assistant turn: time, duration, output tokens, the tools invoked
   in that turn, and a preview of what the assistant said.

Warnings, if any, are shown in a panel at the bottom.

## The `SessionAnalysis` model

`analyze_events(events) -> SessionAnalysis` ([`analysis.py`](../src/copilot_experiments/analysis.py))
produces plain pydantic data (no formatting), so the same object backs the CLI renderer, the
stored `analysis.json`, and any future consumer.

| Field | Meaning |
| --- | --- |
| `session_id`, `copilot_version`, `producer` | Session identity. |
| `models`, `reasoning_effort` | Model(s) observed and the effort level. |
| `repository`, `branch`, `cwd` | Workspace context from `session.start`. |
| `started_at`, `finished_at`, `duration_s` | Span of the session. |
| `n_turns`, `n_user_messages`, `n_assistant_messages` | Conversation counts. |
| `n_tool_calls`, `n_tool_failures` | Tool execution counts (failures correlated by `toolCallId`). |
| `n_warnings`, `n_hooks`, `n_events` | Other counts. |
| `input_tokens`, `output_tokens`, `total_tokens` | Token usage when the log exposes it. |
| `tools` | `ToolStat(name, calls, failures)`, sorted by calls desc. |
| `turns` | `TurnSummary(turn_no, duration_s, tools, output_tokens, text_preview, …)`. |
| `warnings` | Warning messages. |
| `event_type_counts` | Histogram of raw event `type`s. |

## How the session log is read

The Copilot CLI writes a per-session append-only stream of typed events. The fields the
analysis relies on:

| Event | Used for |
| --- | --- |
| `session.start` | `selectedModel`, `reasoningEffort`, `copilotVersion`, `context.{repository,branch,cwd}`, `startTime`. |
| `user.message` | User-message count. |
| `assistant.turn_start` / `assistant.turn_end` | Turn boundaries (and per-turn duration via `turnId`). |
| `assistant.message` | `model`, `content` (preview), `toolRequests`, `outputTokens`. |
| `tool.execution_start` | `toolName` ↔ `toolCallId` mapping; per-turn tool order. |
| `tool.execution_complete` | `success` (correlated back to the tool via `toolCallId`). |
| `session.warning` | Warning messages. |
| `hook.start` | Hook count. |

Parsing is defensive: unknown event types are counted but otherwise ignored, and missing
fields degrade to "unknown" rather than raising. Because the raw `events.jsonl` is always
retained, an improved parser can re-analyze old runs without re-running them.

## Web explorer (TBD)

A browser-based explorer for experiments, runs, session logs, and **aggregated** cross-run data
is planned but **not yet built**. The decision to ship the CLI analysis first and defer the web
app is recorded in [ADR-0007](adr/0007-cli-rich-analysis-before-web-app.md). The groundwork is
deliberately in place:

- `SessionAnalysis` is rendering-agnostic data (ADR-0006), so a web/HTTP layer can serve the
  same model the CLI renders.
- `analysis.json` is persisted per trial, and the SQLite index ([`docs/results-format.md`](results-format.md))
  already supports cross-run queries — the two data sources a web explorer would build on.

When it lands, it will be documented here.
