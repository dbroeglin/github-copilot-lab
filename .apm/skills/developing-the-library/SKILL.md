---
name: developing-the-library
description: >-
  Use when modifying the copilot-experiments library or CLI itself — adding or
  changing modules (models, pier_backend, pier_results, sessionlog, storage,
  report, scaffold, cli), writing tests, or updating the scaffolded
  experiment-repo template. Not for authoring experiments.
---

# Developing the copilot-experiments library

## Mental model
A **run** executes a Pier `JobConfig`. For each agent/task/attempt trial, Pier provisions the
environment, invokes the installed agent, runs the verifier, and downloads logs/artifacts.
`copilot-experiments` contributes the `copilot-cli` Pier agent and derives summaries/analysis from
the resulting `jobs/<job>/<run-id>/` tree.

```
Pier JobConfig ─┬─ tasks/datasets
                └─ agents[] (copilot-cli model, effort, mode, kwargs)
copilot-experiments run → jobs/<job-name>/<run-id>/
```

## Where to make a change
- New Pier config/run behavior → `pier_backend.py`.
- New CLI command/flag → `cli.py` (Typer). `B008` is ignored project-wide for Typer defaults.
- New metric → `sessionlog.parse_metrics` (+ `Metrics` in `models.py`, + `pier_results.py` /
  `report.py` if summaries should expose it).
- New result artifact → emit or collect it through the Pier agent/backend, then document it in
  `docs/results-format.md`.
- Experiment-authoring change → edit `templates/experiment_repo/` (it is package data).

## Testing recipe
- Unit-test pure functions directly (models, sessionlog, storage, scaffold).
- Use Pier config and job-output fixtures for CLI/storage/result tests; mock backend/auth preflights
  instead of invoking Docker or Copilot.
- Build synthetic `events.jsonl` dicts to test `parse_metrics` without any Copilot run.
- Add or update focused offline tests for each behavior change. Good coverage is expected,
  especially around Pier config loading, result adaptation, CLI behavior, and session parsing.

## Verify before done
```bash
uv run ruff check --fix .
uv run ruff format .
uv run ruff check .
uv run pytest -q
# optional end-to-end smoke test:
uv run copilot-experiments init sandbox/demo --force
uv run copilot-experiments validate --root sandbox/demo
```
