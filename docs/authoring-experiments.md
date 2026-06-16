# Authoring experiments

Experiments are **Python objects**, discovered from the `experiments/` directory of an
experiment repository (the kind created by `copilot-experiments init`). Each module exposes one
or more experiments via any of:

- a module-level variable `experiment` (a single `Experiment`), or
- a module-level list `experiments` (multiple `Experiment`s), or
- a function `get_experiments()` returning a list.

## The building blocks

```python
from copilot_experiments import Experiment, Task, Variant
```

### `Task` — what Copilot is asked to do

| Field | Meaning |
| --- | --- |
| `name` | Optional human label; slugified for the results directory (`tasks/<slug>/`). Unnamed tasks become `task-001`, `task-002`, …. |
| `prompt` | The instruction handed to `copilot -p`. |
| `fixture` | Path (relative to the repo) to a directory copied fresh as the starting workspace for every trial. |
| `repo` / `ref` | Alternative to `fixture`: `git clone` a repository and optionally check out a branch/tag/commit. |
| `setup` | Shell commands run in the workspace *after* provisioning, *before* Copilot (e.g. install deps). |
| `verify` | Shell command run *after* Copilot. **Exit code 0 means the trial succeeded.** Omit to skip effectiveness grading. |

Provide either `fixture` **or** `repo` (not both). Keep fixtures deterministic and
self-contained so trials are comparable.

### `Variant` — one cell of the parameter matrix

| Field | Meaning |
| --- | --- |
| `name` | Human label; slugified for the results directory. |
| `model` | e.g. `claude-opus-4.7`, `gpt-5.2`, or a BYOK model id. |
| `reasoning_effort` | `none` / `low` / `medium` / `high` / `xhigh` / `max`. |
| `agent`, `mode` | Optional Copilot agent and mode (`interactive` / `plan` / `autopilot`). |
| `allow_all_tools` | Defaults to `True` (non-interactive runs need tools). |
| `allow_tools` / `deny_tools` | Fine-grained tool gating. |
| `provider` | A `ProviderConfig` for BYOK / local models (see [BYOK guide](byok-and-local-models.md)). |
| `env` | Extra environment variables for this variant. |
| `extra_args` | Raw extra `copilot` CLI arguments. |
| `trials` | Number of repetitions (for statistical robustness). |

### `Experiment`

An experiment is `Tasks × Variants × Trials`. Use the singular `task=` for a single-task
experiment, or `tasks=[...]` to run a **suite** of tasks through the same variant matrix
(exactly one of the two is required).

```python
experiment = Experiment(
    name="Fix the calculator bug",
    description="Copilot must repair a deliberately broken multiply().",
    task=Task(
        prompt="The tests in test_calculator.py fail. Fix calculator.py so they pass.",
        fixture="fixtures/buggy_calculator",
        verify="python -m pytest -q",
    ),
    variants=[
        Variant(name="opus-medium", model="claude-opus-4.7", reasoning_effort="medium", trials=3),
        Variant(name="gpt-5", model="gpt-5.2", trials=3),
    ],
)
```

A task suite — name each task so it gets a stable `tasks/<slug>/` directory:

```python
suite = Experiment(
    name="Calculator fixes",
    description="Several independent bugs, run through the same matrix.",
    tasks=[
        Task(name="Fix multiply", prompt="...", fixture="fixtures/buggy_multiply",
             verify="python -m pytest -q"),
        Task(name="Fix divide", prompt="...", fixture="fixtures/buggy_divide",
             verify="python -m pytest -q"),
    ],
    variants=[Variant(name="opus-medium", model="claude-opus-4.7", trials=3)],
)
```

The report adds two suite-coverage measures per variant: **mean-success** (mean of each task's
trial success rate) and **resolved@k** (the fraction of tasks where *any* trial passed). This is
option B of [ADR-0012](adr/0012-task-suite-as-experiment-axis.md); the sequential runner is best
for handfuls of tasks, not thousands of benchmark instances.

## Workflow

```bash
# 1. Add a deterministic fixture workspace.
mkdir -p fixtures/my_fixture   # put broken code + a test that fails

# 2. Write experiments/my_experiment.py defining `experiment` (as above).

# 3. Validate the whole pipeline without spending credits (persists nothing):
uv run copilot-experiments run --dry-run

# 4. Run for real. The harness preflights GitHub auth first: it uses
#    COPILOT_GITHUB_TOKEN / GH_TOKEN / GITHUB_TOKEN, or falls back to `gh auth token`,
#    and aborts with guidance if none is found. (BYOK provider secrets still come from env.)
uv run copilot-experiments run

# 5. Inspect the produced run:
uv run copilot-experiments show --last
uv run copilot-experiments inspect --last --variant opus-medium --trial 1
```

> **`--dry-run` validates the plumbing, then throws everything away.** It runs the whole
> pipeline with a mock Copilot inside a temp dir and checks each stage produced its artifact
> (workspace + git baseline, session log, metrics, analysis, a **non-empty diff**, verify, run
> summary, index), printing a pass/fail checklist. It does *not* prove task-solving — the mock
> does not solve the task — and it persists nothing under `results/`; use a real `run` to
> capture data to `show`, `analyze`, or `inspect`.

## Tips

- Make `verify` strict and fast (a focused test command) so success is unambiguous.
- Vary **one axis at a time** across variants when you want to attribute differences.
- Use `trials > 1` to smooth out run-to-run variance before comparing models.
- Never edit `results/` by hand; it is regenerable via `copilot-experiments reindex`.
