# Results format

The runner writes a clear, self-describing tree under `results/`. **The filesystem is the
source of truth**; `results/index.db` is a derived SQLite cache that `reindex` rebuilds by
scanning the tree.

## On-disk layout

```
results/
├── index.db                                   # SQLite cross-run index (derived)
└── <experiment-slug>/
    └── <run-id>/                              # run-id = YYYYMMDDTHHMMSSZ_<6hex> (sortable)
        ├── run.json                           # run manifest (ExperimentRun)
        ├── summary.json                       # aggregated metrics per variant
        ├── summary.md                         # human-readable report
        └── variants/
            └── <variant-slug>/
                ├── variant.json               # variant config (secrets redacted)
                └── trials/
                    └── <NNN>/                 # zero-padded trial number, e.g. 001
                        ├── meta.json          # session id, exit code, duration, success
                        ├── prompt.md          # exact prompt sent to Copilot
                        ├── stdout.jsonl       # copilot --output-format json stream
                        ├── events.jsonl       # copied session events (metrics source)
                        ├── metrics.json       # parsed Metrics
                        ├── analysis.json      # SessionAnalysis (rich session overview)
                        ├── workspace.diff      # git diff of Copilot's changes
                        ├── verify.json        # verification command + exit code + output
                        └── workspace/         # the trial's working directory (final state)
```

Terminology: an **experiment** is a Python definition in `experiments/`; an **experiment run**
is one `results/<exp>/<run-id>/`; a **variant** is a parameter combination; a **trial** is one
repetition of a variant.

## Key files

### `run.json`
Serialized `ExperimentRun`: `run_id`, `experiment_slug`/`name`/`description`, `started_at`,
`finished_at`, `git_base` (the experiment repo's HEAD at run time), `status`, and the nested
`variants` → `trials` → `metrics`.

### `metrics.json`
Parsed from `events.jsonl`:

| Field | Meaning |
| --- | --- |
| `n_turns` | Assistant turns (`assistant.turn_start` events). |
| `n_assistant_messages` | Assistant messages. |
| `n_tool_calls` | Completed tool executions. |
| `n_tool_failures` | Tool executions reporting `success: false`. |
| `n_warnings` | `session.warning` events. |
| `models` | Distinct models observed (model changes + per-event model). |
| `duration_s` | Wall-clock span between first and last event. |
| `input_tokens` / `output_tokens` / `total_tokens` | Token usage **if present** in the events (probed defensively; may be `null`). |

### `verify.json`
`{ "command", "exit_code", "success", "output" }`. `success` is `exit_code == 0`. Absent when the
task has no `verify`.

### `analysis.json`
A serialized `SessionAnalysis` — a richer, rendering-agnostic overview of the same
`events.jsonl` (session header, totals, per-tool histogram, and a per-turn timeline). It is what
the `analyze` command renders with Rich, and is the data contract a future web explorer will
consume. See [`docs/analysis.md`](analysis.md) for the field reference.

### `meta.json`
Per-trial summary: `trial_no`, `session_id`, `exit_code`, `duration_s`, `success`, `workspace`.

## SQLite index (`results/index.db`)

A derived, rebuildable index for cross-run queries.

```sql
experiments(slug PK, name, description, first_seen)
runs(run_id PK, experiment_slug, started_at, finished_at, git_base, n_variants, status)
variants(id PK, run_id, variant_slug, model, reasoning_effort, agent, mode, byok, params_json)
trials(id PK, run_id, variant_slug, trial_no, session_id, exit_code, duration_s, success,
       n_turns, n_tool_calls, n_tool_failures, input_tokens, output_tokens, total_tokens, model)
```

Rebuild it any time:

```bash
uv run copilot-experiments reindex
```

### Example queries

```sql
-- Success rate per variant across every run of an experiment:
SELECT variant_slug,
       AVG(success) AS success_rate,
       AVG(duration_s) AS avg_duration_s,
       AVG(n_turns) AS avg_turns
FROM trials
WHERE run_id IN (SELECT run_id FROM runs WHERE experiment_slug = 'fix-the-calculator-bug')
GROUP BY variant_slug;

-- Most expensive trials by total tokens (when token usage is available):
SELECT run_id, variant_slug, trial_no, total_tokens
FROM trials
WHERE total_tokens IS NOT NULL
ORDER BY total_tokens DESC
LIMIT 10;
```

## Secret handling

`variant.json` and the `params_json` column are written via `Variant.stored()`, which masks
`api_key` and `bearer_token` from any BYOK `ProviderConfig`. Secrets are never persisted.
