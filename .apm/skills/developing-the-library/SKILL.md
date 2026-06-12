---
name: developing-the-library
description: >-
  Use when modifying the copilot-experiments library or CLI itself — adding or
  changing modules (models, invoker, runner, sessionlog, storage, index, report,
  scaffold, cli), writing tests, or updating the scaffolded experiment-repo
  template. Not for authoring experiments.
---

# Developing the copilot-experiments library

## Mental model
A **run** executes an `Experiment` (a `Task` + a list of `Variant`s). For each variant, for each
trial, the runner: provisions a workspace → invokes Copilot → copies & parses the session log →
captures a workspace diff → runs `verify` → writes artifacts → updates the SQLite index.

```
Experiment ─┬─ Task (prompt, fixture/repo, setup, verify)
            └─ Variant[] (model, effort, agent, mode, provider/BYOK, env, trials)
run_experiment() → results/<exp>/<run-id>/ + results/index.db
```

## Where to make a change
- New experiment-definition field → `models.py` (+ thread through `invoker.build_args`/`build_env`
  if it affects the command, + `index.py` columns if you want it queryable).
- New CLI command/flag → `cli.py` (Typer). `B008` is ignored project-wide for Typer defaults.
- New metric → `sessionlog.parse_metrics` (+ `Metrics` in `models.py`, + `index.py`, + `report.py`).
- New result artifact → write it in `runner._run_trial`, document it in `storage.py`'s docstring
  and `docs/results-format.md`.
- Experiment-authoring change → edit `templates/experiment_repo/` (it is package data).

## Testing recipe
- Unit-test pure functions directly (models, sessionlog, storage, scaffold).
- For the runner, call `run_experiment(exp, root=tmp, dry_run=True)` for the plumbing path, and
  `run_experiment(exp, root=tmp, invoker=MockInvoker(solver=...))` for a success path.
- Build synthetic `events.jsonl` dicts to test `parse_metrics` without any Copilot run.

## Verify before done
```bash
uv run ruff check . && uv run pytest -q
# optional end-to-end smoke test:
uv run copilot-experiments init sandbox/demo --force
uv run copilot-experiments run --root sandbox/demo --dry-run
```
