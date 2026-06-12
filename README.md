# copilot-experiments

A **library + CLI** for building research experiments that exercise **GitHub Copilot**
(primarily the **Copilot CLI**) and collect results.

Define experiments in Python, run them across a matrix of parameters (different Copilot
models, reasoning efforts, agents, or **BYOK** local models such as Ollama / vLLM), then
collect and analyze the resulting Copilot CLI **session logs** to measure effectiveness,
cost-effectiveness, and failure modes.

> This repository is the **tool**. You author and run actual experiments in a separate
> repository scaffolded with `copilot-experiments init`.

## How it works

```mermaid
flowchart LR
    A["Experiment (Python)\nTask + Variants"] --> B["runner"]
    B -->|"copilot -p --model ... --output-format json"| C["Copilot CLI"]
    C --> D["~/.copilot/session-state/&lt;id&gt;/events.jsonl"]
    B --> E["results/ tree\n(per trial artifacts)"]
    D --> E
    E --> F["results/index.db\n(SQLite index)"]
    E --> G["summary.md / show / inspect"]
```

- An **experiment** is a Python object: a `Task` (prompt + workspace fixture + optional
  `verify` command) and a list of `Variant`s (the parameter matrix).
- The runner provisions an isolated workspace per **trial**, invokes the Copilot CLI
  non-interactively, copies the session `events.jsonl`, captures the workspace diff, runs
  the verification command, and parses metrics.
- Results are written to a clear **filesystem layout** under `results/` and indexed into a
  **SQLite** database for cross-run queries.

## Quickstart

```bash
# install the tool (this repo)
uv sync

# scaffold a new, standalone experiment repository
uv run copilot-experiments init my-experiments
cd my-experiments
uv sync

# dry-run the example experiment (uses a mock Copilot — no credits required)
uv run copilot-experiments run --dry-run
uv run copilot-experiments show --last

# run for real (requires an authenticated `copilot`, or BYOK env vars)
uv run copilot-experiments run
```

## CLI

| Command | Description |
| --- | --- |
| `init <dir>` | Scaffold a new standalone experiment repository. |
| `run [name]` | Discover and run experiment(s) in `experiments/`; writes `results/` + index. |
| `list` | List experiments and past runs. |
| `show <run-id>` / `show --last` | Print a run summary and per-variant comparison. |
| `inspect <run-id>` | Drill into a trial's session events and metrics. |
| `reindex` | Rebuild `results/index.db` from the filesystem. |

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — how the pieces fit together.
- [`docs/authoring-experiments.md`](docs/authoring-experiments.md) — write experiments in Python.
- [`docs/results-format.md`](docs/results-format.md) — the on-disk layout and SQLite schema.
- [`docs/byok-and-local-models.md`](docs/byok-and-local-models.md) — run experiments against BYOK / local models.

## Development

This project is managed with [uv](https://docs.astral.sh/uv/) and uses
[APM](https://github.com/microsoft/apm) for agent context management.

```bash
uv sync
uv run ruff check
uv run pytest
```

See [`AGENTS.md`](AGENTS.md) for agent-oriented contributor guidance.
