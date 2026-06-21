# 0011. Token economics from `session.shutdown`, costed in AIU

- **Status:** Accepted
- **Date:** 2026-06-15
- **Deciders:** project owner, Copilot

## Context

The harness measured *behaviour* (turns, tool calls, failures) but barely touched *cost*. Token
fields were probed defensively from `assistant.message` and were usually `null`, so we could not
answer the questions the Bai et al. paper
([*How Do AI Agents Spend Your Money?*](https://github.com/LongjuBai/agent_token_consumption_analysis))
makes central: where do the tokens go, how much does a task cost, how variable is that cost across
repeated trials, and does spending more actually buy more accuracy.

A close read of real Copilot CLI `events.jsonl` logs (200+ sessions under
`~/.copilot/session-state/`) showed the data is already there, just not where we were looking:

- **`session.shutdown` is authoritative.** It carries `tokenDetails.{input,cache_read,cache_write,
  output}.tokenCount`, a `totalNanoAiu` cost, `totalApiDurationMs`, per-model `modelMetrics`
  (requests + usage incl. `reasoningTokens`), end-of-session context composition
  (`systemTokens`, `conversationTokens`, `toolDefinitionsTokens`, `currentTokens`), and
  `codeChanges.{filesModified,linesAdded,linesRemoved}`. A resumed session emits more than one.
- **Price lives in the log.** `session.compaction_complete` embeds
  `copilotUsage.tokenDetails[].{tokenType,batchSize,costPerBatch}` in nano-AIU — the actual
  per-token-type rates, so we can *decompose* the authoritative total instead of guessing.
- **Per-turn input is not recoverable.** `assistant.message` exposes only `outputTokens`, so a
  phase-level *input* decomposition (one of the paper's analyses) cannot be reconstructed from the
  log and is deliberately out of scope.

Two cost currencies exist historically: premium requests and AIU. GitHub stopped using premium
requests on 2026-06-01, and no `totalPremiumRequests` field appears in current logs.

## Decision

- **Cost is AIU only.** 1 AIU = `totalNanoAiu / 1e9`. Premium requests are ignored entirely. A
  small [`pricing`](../../src/copilot_experiments/pricing.py) module holds the AIU math: documented
  default rates, `rates_from_compaction()` to read live rates, and `aiu_by_type()` which splits the
  authoritative total across token types (normalising so the split always sums to the real total).
- **`session.shutdown` is the source of truth for token totals.** `extract_economics(events)`
  parses it (summing token counts / AIU / requests / api-duration across multiple shutdowns, taking
  the *last* for context composition and code changes) into a rich `TokenEconomics` object, and
  `parse_metrics` copies the flat subset onto `Metrics`. When a shutdown is present its totals
  override the old `assistant.message`-derived token sums; with no shutdown we fall back to the
  previous behaviour and leave economics `null`.
- **Keep the data/rendering split (ADR-0006).** `Metrics` gains ~20 flat scalars (for aggregation
  and the index); the nested `TokenEconomics` hangs off `SessionAnalysis` for rich rendering. Both
  derive from the one `extract_economics` path.
- **Surface it everywhere.** `analyze` gains a *Cost (AIU)* panel and *Session economics* table
  (plus per-tool `dur`/`ctx` columns from `toolTelemetry.metrics`); run summaries and `summary.md`
  gain AIU, cross-trial variance (std / CV), cost-per-solved-task, and productivity columns; the
  SQLite `trials` table gains cost/cache/context/productivity columns for cross-run queries.

## Consequences

- We can now answer the paper's questions for Copilot CLI: cost per task, the input/cache/output
  split (cache-write often dominates), cross-trial variability via CV, and cost-vs-accuracy via
  AIU-per-solve — all from logs we already keep, so old runs can be re-analysed by `reindex`.
- `MockInvoker` now emits a self-consistent `session.shutdown` + `session.compaction_complete`
  (priced with the same `pricing` defaults, so AIU reconciles exactly), keeping the whole economics
  path exercised offline (ADR-0005).
- The index schema grew; because the DB is derived (ADR-0003) this needs no migration — `reindex`
  rebuilds it. The on-disk layout is unchanged.
- **Accepted limitations:** no per-phase *input* decomposition (the log doesn't carry per-turn
  input), and rate normalisation can hide small per-model/tier rate drift inside the by-type split
  while keeping the authoritative grand total exact. AIU is GitHub's internal unit; an optional
  `--usd-per-aiu` conversion is left as a thin future presentation layer.

## Follow-up: OTel per-call economics

On 2026-06-21, `copilot help monitoring` and local file-exporter probes with Copilot CLI
`1.0.64-0` showed an additional optional source: OpenTelemetry `chat <model>` spans carry
per-LLM-call `gen_ai.usage.input_tokens`, `gen_ai.usage.cache_creation_input_tokens`,
`gen_ai.usage.output_tokens`, `github.copilot.nano_aiu`, `github.copilot.server_duration`, and
`github.copilot.turn_id`. In the probes, summing chat spans matched the native
`session.shutdown` totals for input, cache-write, output, nano-AIU, and API duration.

We integrated this as a complement, not a replacement. The harness now enables local OTel file
export to `copilot-otel.jsonl` for Copilot agent runs when no explicit OTLP destination is
configured, and `SessionAnalysis` ingests that file when present to populate a per-call LLM table
and annotate turns with OTel input/cache-write/output/AIU/API-duration fields. Native
`events.jsonl` remains the authoritative source for session-level totals and richer forensic
details; OTel still does not split each call's input into non-cached input versus cache-read tokens.
