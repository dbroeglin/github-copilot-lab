# Architecture

`copilot-experiments` is a small, layered Python package. The filesystem is always the
source of truth; the SQLite index is a derived cache that can be rebuilt at any time.

## Pipeline

```mermaid
flowchart TD
    EXP["Experiment (Python)\nTask(s) + Variant[]"] --> RUN["run_experiment()"]
    RUN --> PROV["workspace.provision()\ncopy fixture / git clone + baseline commit"]
    PROV --> INV["invoker.run()\ncopilot -p --model ... --output-format json"]
    INV --> SS["~/.copilot/session-state/&lt;id&gt;/events.jsonl"]
    SS --> PARSE["sessionlog.parse_metrics()"]
    INV --> DIFF["workspace.capture_diff()"]
    INV --> VERIFY["task.verify (shell, exit 0 = success)"]
    PARSE --> ART["results/&lt;exp&gt;/&lt;run&gt;/.../ artifacts"]
    SS --> ANA["analysis.analyze_events()\n→ analysis.json"]
    ANA --> ART
    DIFF --> ART
    VERIFY --> ART
    ART --> IDX["index.index_run_dir() → results/index.db"]
    ART --> REP["report → summary.json / summary.md"]
    ART --> CLIA["analyze → render.py (Rich)"]
```

## Object model

| Concept | Type | Meaning |
| --- | --- | --- |
| **Experiment** | `Experiment` | A named `Task` (or a `tasks=[...]` suite) plus the matrix of `Variant`s to run them under (`Tasks × Variants × Trials`). |
| **Task** | `Task` | One unit of work: optional `name`, the prompt + how to provision (`fixture` or `repo`/`ref`, `setup`) and `verify` the workspace. |
| **Variant** | `Variant` | One cell of the matrix: `model`, `reasoning_effort`, `agent`, `mode`, tool allow/deny, optional BYOK `provider`, extra `env`, and `trials` (repeat count). |
| **ProviderConfig** | `ProviderConfig` | BYOK settings rendered to `COPILOT_PROVIDER_*` env vars. |
| **Experiment run** | `ExperimentRun` | One execution of an experiment → `results/<exp>/<run-id>/`. |
| **VariantResult / TaskResult / TrialResult** | result models | Per-variant aggregation nests per-task (`TaskResult`) results, each holding per-trial outcomes (+ parsed `Metrics`). |
| **SessionAnalysis** | `SessionAnalysis` | A rendering-agnostic overview of one session log (`ToolStat[]`, `TurnSummary[]`, totals, tokens). Persisted as `analysis.json`. |

## Modules

| Module | Responsibility |
| --- | --- |
| `models.py` | All pydantic schemas (definitions + results). Secret redaction lives here. |
| `workspace.py` | Provision an isolated workspace per trial; commit a git baseline; capture a diff. |
| `invoker.py` | Translate a variant into a `copilot` command and run it. `CopilotInvoker` (real) and `MockInvoker` (dry-run/tests). |
| `sessionlog.py` | Find and parse `events.jsonl` into `Metrics`. |
| `analysis.py` | Derive a rich, rendering-agnostic `SessionAnalysis` from session events. |
| `render.py` | Render a `SessionAnalysis` to the terminal with Rich (used by `analyze`). |
| `runner.py` | Orchestrate variants × tasks × trials and write every artifact. |
| `storage.py` | The `results/` `Layout` and run discovery (`find_run`, `latest_run`). |
| `index.py` | The SQLite schema, insert/reindex, and queries. |
| `report.py` | Aggregate a run into `summary.json` / `summary.md`. |
| `scaffold.py` | `init`: render the experiment-repo template. |
| `cli.py` | The Typer CLI. |

## Two-repo model

- **This repo** is the *tool* (library + CLI). It is installable and developed with `uv`, and
  has its own APM context (`apm.yml`, `.apm/`, `AGENTS.md`) for developing the library.
- **`copilot-experiments init <dir>`** scaffolds a *separate* standalone experiment repository
  (its own `uv` project that depends on this package) where people author and run experiments.
- **`sandbox/`** is a local scratch area for exercising the lib/CLI; its `results/` are gitignored.

## How Copilot CLI is invoked

The Copilot CLI is run non-interactively, one process per trial:

```
copilot -p "<prompt>" --output-format json --session-id <uuid> \
        --log-dir <dir> -C <workspace> [--allow-all-tools] \
        [--model M] [--effort E] [--agent A] [--mode MODE] \
        [--allow-tool T ...] [--deny-tool T ...]
```

- `--session-id` is generated per trial so the rich session stream at
  `~/.copilot/session-state/<id>/events.jsonl` can be copied alongside the trial's artifacts.
- `-C` (and `--log-dir`) are always **absolute** so Copilot's post-cwd `chdir` can't double the
  path (see [ADR-0009](adr/0009-absolute-workspace-path-for-copilot.md)).
- `--log-dir` points at an **ephemeral temp dir**, removed after each trial: Copilot's bulky
  internal debug log is never persisted (see
  [ADR-0010](adr/0010-keep-secrets-and-debug-logs-out-of-results.md)).
- **BYOK** providers are injected purely through `COPILOT_PROVIDER_*` environment variables;
  a variant is therefore just *flags + env*.

## Design invariants

1. **Filesystem is canonical.** `reindex` rebuilds `results/index.db` by scanning `results/`.
2. **Secrets are never stored.** `Variant.stored()` / `ProviderConfig.redacted()` mask keys.
3. **Offline-testable.** `MockInvoker` simulates a run (synthetic `events.jsonl`), so the test
   suite and dry-runs need no Copilot credits or network.
4. **Ephemeral dry-runs.** A `--dry-run` exercises the whole pipeline in a throwaway temp dir,
   validates each stage's artifact, then deletes everything — no run is persisted under
   `results/`. See [ADR-0008](adr/0008-dry-run-is-ephemeral-plumbing-check.md).
5. **Analysis data is split from rendering.** `analysis.py` produces plain data; `render.py`
   (Rich) and the persisted `analysis.json` consume it, so a future web explorer can reuse the
   same model. See [ADR-0006](adr/0006-separate-analysis-data-from-rendering.md) and
   [ADR-0007](adr/0007-cli-rich-analysis-before-web-app.md).

## Decisions

Architecture decisions are recorded under [`adr/`](adr). See the
[ADR index](adr/README.md) for the full list.
