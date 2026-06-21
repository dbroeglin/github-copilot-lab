# Results format

For new runs, Pier job directories under `jobs/` are the filesystem source of truth. The SQLite
database under `results/index.db` is a derived cache.

For a source-by-source explanation of what can be captured around a Copilot CLI run, see
[Collecting data from a Copilot CLI run](collecting-run-data.md).

## Pier job layout

```
jobs/
  <job-name>/
    config.json
    result.json
    summary.json          # written by copilot-experiments
    summary.md            # written by copilot-experiments
    <trial-name>/
      config.json
      result.json
      agent/
        copilot-cli.jsonl
        copilot-cli.txt
        trajectory.json
        copilot-otel.jsonl   # Copilot OTel file export, when no custom OTLP destination overrides it
        copilot-session/
          <session-id>/
            events.jsonl
      verifier/
        reward.txt
        reward.json
      artifacts/
```

Pier owns `config.json`, `result.json`, trial directories, logs, verifier outputs, and artifact
download. `copilot-experiments` derives summaries and indexes from that tree.

## Key files

| File | Meaning |
| --- | --- |
| `jobs/<job>/result.json` | Pier job-level status and stats. |
| `jobs/<job>/<trial>/result.json` | Pier trial status, agent info, verifier result, exceptions, timings. |
| `agent/trajectory.json` | ATIF trajectory emitted by the installed agent. Used as a fallback for non-Copilot agents. |
| `agent/copilot-cli.jsonl` / `.txt` | Raw Copilot CLI output streams. Useful for auth or CLI failures. |
| `agent/copilot-session/**/events.jsonl` | Native Copilot session log. Primary source for Copilot turns, tool calls, tokens, AIU, and analysis. |
| `agent/copilot-otel.jsonl` | Copilot OTel file-exporter output, captured by default for Copilot agent runs unless custom OTel destination settings override it. Useful for per-LLM-call spans with input/output/cache-write/nano-AIU details. |
| `verifier/reward.txt` / `.json` | Pier verifier reward. Positive reward means solved. |
| `summary.json` / `summary.md` | Derived summary in the familiar variant/task aggregate shape. |

Pier jobs do not persist per-trial `metrics.json` or `analysis.json` files. Those views are
derived from `agent/copilot-session/**/events.jsonl` (or `agent/trajectory.json` as a fallback)
when `show`, `analyze`, `inspect`, or `reindex` runs. Legacy Python runs still keep those files in
their `results/<experiment>/<run>/.../trials/<NNN>/` layout.

## Summary shape

`summary.json` contains:

- job identity and status (`run_id`, `experiment`, `started_at`, `finished_at`);
- aggregate counts (`n_variants`, `n_tasks`, `n_trials`, failures);
- `overall_success_rate` from verifier rewards;
- one entry per agent/model variant;
- one task aggregate per variant;
- Copilot-native token/AIU/tool metrics when native events are available;
- nullable fallback metrics for non-Copilot agents.

## SQLite index

`reindex` rebuilds `results/index.db` from both `jobs/` and legacy `results/`.

New Pier tables:

```sql
pier_jobs(job_name PK, job_dir, started_at, finished_at, n_trials, success_rate, status)
pier_trials(id PK, job_name, variant_slug, task_slug, trial_name, success, status,
            n_turns, n_tool_calls, total_tokens, aiu, model, error)
```

Legacy tables (`experiments`, `runs`, `variants`, `tasks`, `trials`) remain for old Python runs.

## Analyzing a trial

```bash
uv run copilot-experiments analyze --last --trial 1
uv run copilot-experiments analyze <job-name> --trial 1
uv run copilot-experiments analyze --file jobs/<job>/<trial>/agent/copilot-session/.../events.jsonl
```

If the selected Pier trial has no native Copilot `events.jsonl`, `analyze` falls back to
`agent/trajectory.json` when present; otherwise it reports that no Copilot session log or
trajectory is available.
