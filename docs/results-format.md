# Results format

Pier job directories under `jobs/` are the filesystem source of truth. `copilot-experiments`
derives summaries on demand from Pier results and Copilot-native logs; there is no separate result
index to rebuild.

For a source-by-source explanation of what can be captured around a Copilot CLI run, see
[Collecting data from a Copilot CLI run](collecting-run-data.md).

## Pier job layout

```
jobs/
  <job-name>/
    <run-id>/
      config.json
      result.json
      copilot-experiments-run.json
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
download. `copilot-experiments` adds `copilot-experiments-run.json` to preserve the stable
`job_name` plus concrete `run_id`, then derives summaries from that tree.

## Key files

| File | Meaning |
| --- | --- |
| `jobs/<job>/<run-id>/result.json` | Pier job-level status and stats for one execution. |
| `jobs/<job>/<run-id>/copilot-experiments-run.json` | Stable job name and concrete run id used by summaries and lookup. |
| `jobs/<job>/<run-id>/<trial>/result.json` | Pier trial status, agent info, verifier result, exceptions, timings. |
| `agent/trajectory.json` | ATIF trajectory emitted by the installed agent. Copilot agent steps include OTel per-LLM-call metrics when `copilot-otel.jsonl` is available; the file is also used as a fallback for non-Copilot agents. |
| `agent/copilot-cli.jsonl` / `.txt` | Raw Copilot CLI output streams. Useful for auth or CLI failures. |
| `agent/copilot-session/**/events.jsonl` | Native Copilot session log. Primary source for Copilot turns, tool calls, tokens, AIU, and analysis. |
| `agent/copilot-otel.jsonl` | Copilot OTel file-exporter output, captured by default for Copilot agent runs unless custom OTel destination settings override it. Useful for per-LLM-call spans with input/output/cache-write/nano-AIU details. |
| `verifier/reward.txt` / `.json` | Pier verifier reward. Positive reward means solved. |
| `summary.json` / `summary.md` | Derived agent/task aggregate summary. |

Pier jobs do not persist per-trial `metrics.json` or `analysis.json` files. Those views are
derived from `agent/copilot-session/**/events.jsonl` (or `agent/trajectory.json` as a fallback)
when `show`, `analyze`, or `inspect` runs.

## Summary shape

`summary.json` contains:

- job identity and status (`job`, `job_name`, `run_id`, `started_at`, `finished_at`);
- aggregate counts (`n_agents`, `n_tasks`, `n_trials`, failures);
- `overall_success_rate` from verifier rewards;
- one entry per Pier agent;
- one task aggregate per agent;
- Copilot-native token/AIU/tool metrics when native events are available;
- nullable fallback metrics for non-Copilot agents.

## Analyzing a trial

```bash
uv run copilot-experiments list
uv run copilot-experiments analyze --last --agent copilot-cli --trial 1
uv run copilot-experiments analyze <job-name> --agent copilot-cli --trial 1
uv run copilot-experiments analyze <job-name>/<run-id> --agent copilot-cli --trial 1
uv run copilot-experiments analyze --file jobs/<job>/<run-id>/<trial>/agent/copilot-session/.../events.jsonl
```

`list` is the discovery command for run ids. For Pier outputs, its `selector (job/run)` column is
the exact string accepted by `show`, `inspect`, and `analyze`. Passing only `<job-name>` selects
that job's latest run; passing `<job-name>/<run-id>` selects one concrete execution. Use
`inspect <selector>` to discover exact `--agent`, `--task`, and `--trial` values before calling
`analyze`.

If the selected Pier trial has no native Copilot `events.jsonl`, `analyze` falls back to
`agent/trajectory.json` when present; otherwise it reports that no Copilot session log or
trajectory is available. When Pier recorded a trial exception before the agent ran, `analyze`
includes that harness error and points at the trial `result.json`.
