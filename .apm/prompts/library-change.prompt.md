---
description: Add or modify a module in the copilot-experiments library.
---

# Library change

Make a change to the `copilot_experiments` package (the harness, not an experiment).

Steps:
1. Identify the right module (see `AGENTS.md` repository map and the
   `developing-the-library` skill).
2. Implement the change, keeping the architecture invariants intact (filesystem is source of
   truth; secrets redacted on disk; tests/dry-runs stay offline).
3. Add or update tests in `tests/` using `MockInvoker` and a temp `--root`.
4. Run `uv run ruff check .` and `uv run pytest -q`; fix until both are green.
5. Update `docs/`, `README.md`, and the `templates/experiment_repo/` template if public
   behavior changed.
