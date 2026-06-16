---
name: authoring-experiments
description: >-
  Use when creating or editing a GitHub Copilot experiment in this repository:
  defining the Task (prompt, fixture, setup, verify) and the matrix of Variants
  (model, reasoning effort, agent, or BYOK provider).
---

# Authoring experiments

An experiment is an `Experiment` object combining one or more `Task`s with a list of `Variant`s
(`Tasks × Variants × Trials`). Use `task=` for a single task, or `tasks=[...]` for a suite.

## Task
- `name` — optional label; sets the `tasks/<slug>/` results dir (unnamed → `task-001`, …).
- `prompt` — the instruction handed to `copilot -p`.
- `fixture` — directory (relative to the repo) copied as the starting workspace; OR
  `repo` + `ref` to clone a git repository instead.
- `setup` — optional shell commands run in the workspace before Copilot.
- `verify` — optional shell command run after Copilot; exit code 0 == success. This is how
  effectiveness is measured, so make it strict (e.g. `python -m pytest -q`).

## Variant (the parameter matrix)
- `model` — e.g. `claude-opus-4.7`, `gpt-5.2`, or a BYOK model name.
- `reasoning_effort` — `none|low|medium|high|xhigh|max`.
- `agent`, `mode` — optional Copilot agent/mode.
- `provider` — a `ProviderConfig` for BYOK / local models (Ollama, vLLM, Azure, Anthropic).
- `trials` — number of repetitions (for statistical robustness).

## Skeleton
```python
from copilot_experiments import Experiment, Task, Variant

experiment = Experiment(
    name="My task",
    task=Task(prompt="...", fixture="fixtures/my_fixture", verify="python -m pytest -q"),
    variants=[
        Variant(name="opus", model="claude-opus-4.7", reasoning_effort="medium", trials=3),
        Variant(name="gpt", model="gpt-5.2", trials=3),
    ],
)
```

## Task suite (multiple tasks)
Run several tasks through the same variant matrix. The report adds **mean-success** (mean
per-task success) and **resolved@k** (fraction of tasks any trial solved) columns.
```python
suite = Experiment(
    name="My suite",
    tasks=[
        Task(name="Task A", prompt="...", fixture="fixtures/a", verify="python -m pytest -q"),
        Task(name="Task B", prompt="...", fixture="fixtures/b", verify="python -m pytest -q"),
    ],
    variants=[Variant(name="opus", model="claude-opus-4.7", trials=3)],
)
```

## Validate
```bash
copilot-experiments run --dry-run   # mock invoker; checks plumbing, no credits
```
