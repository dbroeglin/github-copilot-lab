---
description: How to work in a copilot-experiments repository.
applyTo: "**"
---

# Working in this experiment repository

- Experiments are Python objects in `experiments/*.py` built from `copilot_experiments`.
- A starting workspace lives under `fixtures/<name>/` and is copied fresh for every trial.
- Generated data lives under `results/` and must not be edited by hand.

When adding an experiment:
1. Create a deterministic, self-contained fixture under `fixtures/`.
2. Define a `Task` (prompt, `fixture`, optional `setup`, `verify`) and a list of `Variant`s.
3. Prefer a `verify` shell command that exits non-zero on failure (e.g. a test run).
4. Validate the pipeline with `copilot-experiments run --dry-run` before a real run.
