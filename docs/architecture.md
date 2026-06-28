# Architecture

`copilot-experiments` is a thin integration layer around Pier. Pier provides the execution
substrate; this package contributes a GitHub Copilot CLI installed agent, Copilot-native session
analysis, a small CLI, templates, and derived reporting.

## Pipeline

```mermaid
flowchart TD
    TASK["Harbor/Pier task directory\ntask.toml + instruction.md + environment/ + tests/"] --> CFG["Pier JobConfig\nexperiments/*.yaml"]
    CFG --> JOB["pier.job.Job"]
    JOB --> ENV["Pier environment\nDocker / Modal / Daytona"]
    JOB --> AGENT["installed agent\ncopilot-cli or another Pier agent"]
    AGENT --> CLI["real copilot CLI\n-p --output-format json --session-id --log-dir"]
    CLI --> STATE["~/.copilot/session-state/<id>/events.jsonl"]
    CLI --> OTEL["/logs/agent/copilot-otel.jsonl"]
    STATE --> EVENTS["/logs/agent/copilot-session/<id>/events.jsonl"]
    AGENT --> ATIF["/logs/agent/trajectory.json"]
    OTEL --> ATIF
    JOB --> VERIFY["Pier verifier\ntests/test.sh -> reward.txt/json"]
    JOB --> OUT["jobs/<job>/<run-id>/<trial>/"]
    EVENTS --> ANALYSIS["sessionlog.py + analysis.py"]
    OTEL --> ANALYSIS
    ATIF --> FALLBACK["ATIF fallback metrics"]
    OUT --> SUMMARY["pier_results.py\nsummary.json / summary.md"]
```

## Main modules

| Module | Responsibility |
| --- | --- |
| `pier_agents/copilot_cli.py` | Pier `BaseInstalledAgent` that installs and runs the real Copilot CLI, captures native session logs, and emits ATIF. |
| `pier_backend.py` | Discovers and normalizes Pier `JobConfig` YAML/JSON, maps `name: copilot-cli` to the local import path, injects Copilot auth, and calls Pier's Python API. |
| `pier_results.py` | Reads Pier job directories and derives job/run/agent/task/trial summaries. |
| `sessionlog.py` | Parses native Copilot `events.jsonl` into flat metrics, including AIU/token economics. |
| `analysis.py` / `render.py` | Builds and renders a richer session analysis view from native Copilot events. |
| `storage.py` | Locates canonical Pier `jobs/<job>/<run-id>/` directories. |
| `scaffold.py` | Renders a Pier-first experiment repository template. |
| `cli.py` | Typer CLI for init/deepswe-import/validate/run/list/show/inspect/analyze. |

Legacy native `Experiment`, `Task`, `Variant`, `runner.py`, `workspace.py`, `invoker.py`, and the
SQLite index have been removed from active code paths. All execution goes through Pier jobs.

## Copilot CLI installed agent

The local agent is available as:

```yaml
agents:
  - name: copilot-cli
    model_name: gpt-5-mini
    kwargs:
      reasoning_effort: low
```

During normalization, `name: copilot-cli` becomes
`copilot_experiments.pier_agents.copilot_cli:CopilotCli`. The agent:

- installs Copilot CLI through the official installer;
- allowlists GitHub/Copilot domains for Pier network policy;
- runs `copilot -p <instruction> --output-format json --session-id <uuid> --log-dir
  /logs/agent/copilot-session`;
- copies `~/.copilot/session-state/<uuid>/` into `/logs/agent/copilot-session/<uuid>/` so the
  native `events.jsonl` is persisted with the Pier trial;
- supports model, effort, mode, context tier, MCP config, skills, and extra CLI args through Pier
  agent kwargs;
- writes raw CLI JSONL/text, ATIF `trajectory.json`, and native Copilot session logs;
- writes Copilot OTel file-exporter output to `/logs/agent/copilot-otel.jsonl` by default when no
  explicit OTLP destination is configured, so `analyze` can show per-LLM-call economics and
  `trajectory.json` can annotate matching assistant steps with those per-call metrics.

## Design invariants

1. **Pier jobs are canonical.** `jobs/<job>/<run-id>/` is the primary source of truth for new runs.
2. **Copilot logs are primary for Copilot metrics.** ATIF is a fallback and cross-agent view.
3. **Copilot CLI is not reimplemented.** The installed agent shells out to the real CLI.
4. **Tests stay offline.** Unit tests use config and job fixtures, not Docker or real Copilot.
5. **Secrets stay out of persisted config.** Auth is injected at run time via environment.
