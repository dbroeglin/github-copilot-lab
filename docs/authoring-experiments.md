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

## Workflow

```bash
# 1. Add a deterministic fixture workspace.
mkdir -p fixtures/my_fixture   # put broken code + a test that fails

# 2. Write experiments/my_experiment.py defining `experiment` (as above).

# 3. Validate the plumbing with a mock run (no credits, no network):
uv run copilot-experiments run --dry-run

# 4. Inspect the produced run:
uv run copilot-experiments show --last
uv run copilot-experiments inspect --last --variant opus-medium --trial 1

# 5. Run for real (needs an authenticated `copilot`, or BYOK env):
uv run copilot-experiments run
```

> **Dry-runs use a mock Copilot.** By default the mock does *not* solve the task, so `verify`
> will report failure — that is expected. A dry-run validates the harness plumbing (workspace,
> artifacts, metrics, index), not task-solving.

## Tips

- Make `verify` strict and fast (a focused test command) so success is unambiguous.
- Vary **one axis at a time** across variants when you want to attribute differences.
- Use `trials > 1` to smooth out run-to-run variance before comparing models.
- Never edit `results/` by hand; it is regenerable via `copilot-experiments reindex`.
