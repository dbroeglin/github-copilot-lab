---
description: How to develop the copilot-experiments library and CLI.
applyTo: "**"
---

# Developing copilot-experiments

This repo is the **tool** (library + Typer CLI), developed with `uv`. It is not an
experiment repo — experiment-authoring context is a template under
`src/copilot_experiments/templates/experiment_repo/`.

## Always
- Run `uv run ruff check --fix .`, `uv run ruff format .`, `uv run ruff check .`, and
  `uv run pytest -q` before considering work done; keep all green.
- Treat perfectly linted/formatted code as non-negotiable. Ruff owns Python linting and
  formatting, and CI/pre-commit enforce it.
- Maintain good test coverage for every behavior change with focused offline tests, not just broad
  smoke coverage.
- Keep tests offline: exercise the runner with `MockInvoker` (and a `solver` for the success
  path) plus a temp `--root`. Never invoke the real `copilot` binary or the network in tests.
- Preserve invariants: filesystem is source of truth (`reindex` rebuilds `index.db`); secrets are
  redacted on disk (`Variant.stored()` / `ProviderConfig.redacted()`); `--dry-run` is ephemeral —
  it runs in a temp dir, validates each stage, and persists nothing (`dry_run_experiment`).

## When changing public behavior
- Update `docs/` (architecture, authoring, results-format, BYOK) and `README.md`.
- Mirror experiment-authoring changes in the `templates/experiment_repo/` assets.
- Bump `__version__` in `src/copilot_experiments/__init__.py` and `version` in `pyproject.toml`.

## Module responsibilities
`models` (schemas) · `invoker` (build/run copilot) · `workspace` (provision + diff) ·
`sessionlog` (parse events → metrics) · `runner` (orchestrate) · `storage` (layout) ·
`index` (sqlite) · `report` (summaries) · `scaffold` (init) · `cli` (Typer).
