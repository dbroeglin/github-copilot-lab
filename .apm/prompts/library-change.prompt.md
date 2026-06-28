---
description: Add or modify a module in the copilot-experiments library.
---

# Library change

Make a change to the `copilot_experiments` package (the harness, not an experiment).

Steps:
1. Identify the right module (see `AGENTS.md` repository map and the
   `developing-the-library` skill).
2. Implement the change, keeping the architecture invariants intact (`jobs/<job>/<run-id>/` is the
   filesystem source of truth; secrets are redacted on disk; tests stay offline).
3. Add or update tests in `tests/` using fixtures/mocks and a temp `--root`.
4. Run `uv run ruff check --fix .`, `uv run ruff format .`, `uv run ruff check .`, and
   `uv run pytest -q`; fix until all are green.
5. Update `docs/`, `README.md`, and the `templates/experiment_repo/` template if public
   behavior changed.
