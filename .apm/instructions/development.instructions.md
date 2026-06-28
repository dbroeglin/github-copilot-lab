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
- Keep tests offline: use Pier config/job-output fixtures and mocks plus a temp `--root`. Never
  invoke the real `copilot` binary, Docker, or the network in tests.
- Preserve invariants: `jobs/<job>/<run-id>/` is the filesystem source of truth; summaries are
  derived; secrets are injected at run time and redacted from persisted configs.

## When changing public behavior
- Update `docs/` (architecture, authoring, results-format, BYOK) and `README.md`.
- Mirror experiment-authoring changes in the `templates/experiment_repo/` assets.
- Bump `__version__` in `src/copilot_experiments/__init__.py` and `version` in `pyproject.toml`.

## Module responsibilities
`models` (analysis/economics schemas) · `pier_backend` (Pier config/run integration) ·
`pier_results` (job/run/agent/task summaries) · `sessionlog` (parse events → metrics) ·
`storage` (Pier jobs layout) · `report` (summaries) · `scaffold` (init) · `cli` (Typer).
