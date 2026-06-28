# Session-log analysis

After a Pier trial runs with the local `copilot-cli` agent, the job output keeps the native
Copilot CLI **session log** (`agent/copilot-session/**/events.jsonl`). `copilot-experiments`
derives two views from that raw log:

- **Flat metrics** — counters used for `summary.json` and `show`.
- **`SessionAnalysis`** — a richer, structured overview of *what happened* in the session,
  rendered by `analyze`.

Pier runs derive these views from the canonical job artifacts on demand.

This page covers the second one and the `analyze` command that renders it.

> Why a session log at all, and why split data from rendering? See
> [ADR-0004](adr/0004-session-log-is-primary-data-source.md) and
> [ADR-0006](adr/0006-separate-analysis-data-from-rendering.md).
> For the broader collection playbook, including raw `events.jsonl`, stdout,
> `--share`, debug logs, workspace diffs, verification output, and OpenTelemetry,
> see [Collecting data from a Copilot CLI run](collecting-run-data.md).

## The `analyze` command

```bash
# Most recent Pier run; add selectors when multiple trials match
uv run copilot-experiments analyze --last --agent copilot-cli --trial 1

# Discover copyable selectors
uv run copilot-experiments list

# A specific Pier job's latest run / trial
uv run copilot-experiments analyze tracer-bullet-textstats --agent copilot-cli --trial 1

# A specific Pier run / trial
uv run copilot-experiments analyze tracer-bullet-textstats/20260620-153000 --agent copilot-cli --trial 1

# Any events.jsonl on disk — a stored trial log, or a live session under
# ~/.copilot/session-state/<id>/events.jsonl
uv run copilot-experiments analyze --file path/to/events.jsonl

# Direct file analysis enriched with OTel per-LLM-call spans
uv run copilot-experiments analyze --file path/to/events.jsonl --otel-file path/to/copilot-otel.jsonl

# Long sessions: cap the timeline table
uv run copilot-experiments analyze --last --max-turns 15
```

The rendering (built with [Rich](https://rich.readthedocs.io/)) has these parts:

1. **Header** — session id, model(s), reasoning effort, repo/branch, Copilot version, start
   time, and wall-clock duration.
2. **Totals** — turns, user/assistant messages, tool calls, tool failures, warnings, hooks,
   tokens, and total event count.
3. **Tool usage** — a histogram of how often each tool was invoked and how often it failed,
   plus the total wall-clock time it spent (`dur`) and the size of the results it fed back to the
   model (`ctx`, from `toolTelemetry.metrics` — a proxy for the input-token cost each tool injects).
4. **Token economics** — *only when the log carries a `session.shutdown`*. A **Cost (AIU)** table
   decomposing spend across the four token types (input / cache-read / cache-write / output) with
   each type's token count and share of cost, plus a **Session economics** table (requests, API
   time, ms/request, current & peak context, system/tool-definition tokens, compactions,
   truncations, files modified, lines ±, AIU per line). Multi-model sessions also get a per-model
   table. See [ADR-0011](adr/0011-token-economics-from-session-shutdown.md).
5. **LLM calls (OTel)** — *only when `copilot-otel.jsonl` is available.* One row per `chat <model>`
   span with turn id, model, input tokens, cache-read/cache-write tokens when exported, output and
   total tokens, AIU, wall/API time, and current/limit context size.
6. **Phases (temporal)** — *only when the session has at least five turns.* The turns are split
   into five contiguous, near-equal groups (`early` → `later`) and each phase shows its turn span,
   tool calls, output tokens, share of total output, and duration. This mirrors the phase-level
   analysis in Bai et al. (their Finding #6: context construction dominates early phases,
   generation later ones) — tool-heavy, low-output early phases give way to higher output-share
   later ones. See the limitation note below.
7. **Timeline** — one row per assistant turn: time, duration, output tokens, the tools invoked
   in that turn, and a preview of what the assistant said.

Warnings, if any, are shown in a panel at the bottom.

> **Phases use native per-turn data only — no per-phase input/cache/cost yet.** Native
> `events.jsonl` logs input, cache, reasoning, and AIU **only as session totals**
> (`session.shutdown`), never per turn; the per-turn `assistant.message` carries `outputTokens` but
> not `inputTokens`. Copilot's OTel `chat <model>` spans expose per-LLM-call `input_tokens`,
> optional cache-read details, `cache_creation_input_tokens`, `output_tokens`, `nano_aiu`, and
> server duration when OTel export is enabled; `analyze` auto-loads the harness-captured
> `copilot-otel.jsonl` when present, or accepts
> `--otel-file` for direct log analysis. The current phase table still distributes only the native
> per-turn signals — output tokens, tool activity, and duration — and deliberately does **not**
> fabricate per-phase input or cost. The separate **LLM calls (OTel)** table carries the per-call
> economics.

> **A blank "assistant said" is normal — it is not a missing-data bug.** Many turns invoke a
> tool without any accompanying prose, so the assistant text is genuinely empty and the row
> shows only the tool it called. *Reasoning* models (e.g. OpenAI's `gpt-5*` family) do this on
> almost every turn and additionally keep their chain-of-thought in encrypted fields
> (`reasoningOpaque` / `encryptedContent`) that are not human-readable by design; chattier
> models (e.g. Claude) narrate alongside most tool calls. This is a property of the model, not
> of the harness, and it does **not** affect any measured metric — token counts and AIU come
> from `session.shutdown`, and the `tools` column still shows what each turn did. We
> deliberately do **not** force readable output on (e.g. via `--enable-reasoning-summaries`),
> because emitting extra text would perturb the very token economics we measure.

> **Cost is measured in AIU** (GitHub's billing unit; `totalNanoAiu / 1e9`). Premium requests are
> ignored — GitHub stopped using them on 2026-06-01.

## The `SessionAnalysis` model

`analyze_events(events) -> SessionAnalysis` ([`analysis.py`](../src/copilot_experiments/analysis.py))
produces plain pydantic data (no formatting), so the same object backs the CLI renderer and any
future consumer.

| Field | Meaning |
| --- | --- |
| `session_id`, `copilot_version`, `producer` | Session identity. |
| `models`, `reasoning_effort` | Model(s) observed and the effort level. |
| `repository`, `branch`, `cwd` | Workspace context from `session.start`. |
| `started_at`, `finished_at`, `duration_s` | Span of the session. |
| `n_turns`, `n_user_messages`, `n_assistant_messages` | Conversation counts. |
| `n_tool_calls`, `n_tool_failures` | Tool execution counts (failures correlated by `toolCallId`). |
| `n_warnings`, `n_hooks`, `n_events` | Other counts. |
| `input_tokens`, `output_tokens`, `total_tokens` | Token usage (authoritative from `session.shutdown` when present). |
| `economics` | `TokenEconomics`: token-type split, AIU cost, context composition, productivity (see below). |
| `tools` | `ToolStat(name, calls, failures, total_duration_ms, total_result_chars)`, sorted by calls desc. |
| `llm_calls` | `LlmCallSummary` rows parsed from OTel `chat <model>` spans when `copilot-otel.jsonl` is available. |
| `turns` | `TurnSummary(turn_no, duration_s, tools, output_tokens, text_preview, …)` plus OTel `input_tokens`, optional `cache_read_input_tokens`, `cache_creation_input_tokens`, `aiu`, and `api_duration_ms` when available. |
| `phases` | `PhaseStat(name, turn_from, turn_to, n_turns, n_tool_calls, output_tokens, duration_s, output_share)` — five temporal phases (empty for sessions under five turns). |
| `warnings` | Warning messages. |
| `event_type_counts` | Histogram of raw event `type`s. |

### `TokenEconomics`

Parsed by `extract_economics(events)` from `session.shutdown` (authoritative; summed across
multiple shutdowns when a session was resumed) plus `session.compaction_*` / `session.truncation`.
Every field is best-effort — a session with no shutdown leaves the totals `null`.

| Field | Meaning |
| --- | --- |
| `input_tokens_noncached`, `cache_read_tokens`, `cache_write_tokens`, `output_tokens` | The four metered token types. |
| `reasoning_tokens` | Reasoning tokens (a subset of output). |
| `input_tokens_total`, `total_tokens` | Billed input (non-cached + cache read + cache write) and the grand total. |
| `aiu`, `aiu_by_type` | Total AIU cost and its decomposition across token types (sums to `aiu`). |
| `api_duration_ms`, `n_requests` | Model API wall-clock and request count. |
| `system_tokens`, `tool_definitions_tokens`, `conversation_tokens`, `context_tokens` | End-of-session context-window composition. |
| `peak_context_tokens` | Largest context observed (from compaction/truncation pre-sizes). |
| `n_compactions`, `n_truncations`, `compaction_aiu`, `tokens_removed_truncation` | Context-management dynamics and their cost. |
| `files_modified`, `lines_added`, `lines_removed` | Productivity, from `codeChanges`. |
| `model_metrics` | Per-model `ModelMetric(requests, input/output/cache/reasoning tokens, aiu)`. |

The AIU math lives in [`pricing.py`](../src/copilot_experiments/pricing.py): it reads live
per-token-type rates from `session.compaction_complete` (`costPerBatch`) when available, falls back
to documented defaults otherwise, and normalises the split so it always sums to the authoritative
`totalNanoAiu`. See [ADR-0011](adr/0011-token-economics-from-session-shutdown.md).

Pier `agent/trajectory.json` carries the same OTel facts when the local file export is present.
Assistant steps matched by `turnId` get ATIF `metrics.prompt_tokens`, `metrics.completion_tokens`,
`llm_call_count`, and `metrics.extra.copilot_otel`; `final_metrics.extra.copilot_otel` stores the
aggregate per-call totals. The native `events.jsonl` path remains authoritative for session-level
totals when a `session.shutdown` exists.

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
| `tool.execution_complete` | `success` (correlated back to the tool via `toolCallId`); `toolTelemetry.metrics.{durationMs,resultForLlmLength}` for per-tool latency and context size. |
| `session.warning` | Warning messages. |
| `hook.start` | Hook count. |
| `session.shutdown` | **Authoritative token economics:** `tokenDetails` per type, `totalNanoAiu`, `totalApiDurationMs`, `modelMetrics`, context composition, `codeChanges`. |
| `session.compaction_complete` | Live per-token AIU rates (`costPerBatch`), compaction cost, and context peak. |
| `session.truncation` | Truncation count, tokens removed, context peak. |

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
- Pier jobs keep raw native session logs plus ATIF trajectories, while the SQLite index
  ([`docs/results-format.md`](results-format.md)) already supports cross-run queries — the two
  data sources a web explorer would build on.

When it lands, it will be documented here.
