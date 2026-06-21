# Authoring experiments

New experiments are Pier jobs over Harbor/Pier task directories.

## Repository layout

```
experiments/
  my-job.yaml
tasks/
  fix-calculator/
    task.toml
    instruction.md
    environment/
      Dockerfile
      calculator.py
    tests/
      test.sh
      test_calculator.py
jobs/       # Pier outputs, gitignored
results/    # derived SQLite index, gitignored
```

## Task directory

`task.toml` describes metadata and resource limits:

```toml
version = "1.0"

[task]
name = "examples/fix-calculator"
description = "Fix a small Python bug."
authors = [{ name = "example" }]
keywords = ["copilot", "python"]

[metadata]
difficulty = "easy"

[agent]
timeout_sec = 600.0

[verifier]
timeout_sec = 120.0

[environment]
build_timeout_sec = 600.0
cpus = 1
memory_mb = 2048
storage_mb = 10240
gpus = 0
allow_internet = true
workdir = "/app"
```

`instruction.md` is the prompt handed to the agent. Keep hidden verifier details out of it when
benchmarking.

`environment/Dockerfile` builds the starting workspace. A minimal Python task usually copies the
buggy source into `/app`.

`tests/test.sh` is the Pier verifier. It should write a reward and exit non-zero on failure:

```bash
#!/usr/bin/env bash
set +e

python -m pip install --quiet pytest==8.4.1
python -m pytest -q /tests/test_calculator.py
status=$?

if [ "$status" -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi

exit "$status"
```

## Job config

`experiments/my-job.yaml` is a Pier `JobConfig`:

```yaml
job_name: fix-calculator
jobs_dir: jobs
n_attempts: 3
n_concurrent_trials: 2

agents:
  - name: copilot-cli
    model_name: gpt-5-mini
    kwargs:
      reasoning_effort: low

tasks:
  - path: ../tasks/fix-calculator

artifacts:
  - source: /app/calculator.py
    destination: calculator.py
```

Useful knobs:

| Field | Meaning |
| --- | --- |
| `agents[]` | Pier agents to run. `name: copilot-cli` maps to this package's local installed agent. Other Pier agents can be used for success/reward capture even without Copilot-native metrics. |
| `model_name` | Model passed to the agent. For Copilot CLI this becomes `--model`. |
| `kwargs.reasoning_effort` | Copilot `--effort`. |
| `kwargs.mode` | Copilot `--mode` (`plan`, `interactive`, `autopilot`). |
| `kwargs.context_tier` | Copilot context-window tier (`default` or `long_context`). |
| `kwargs.extra_args` | Raw extra Copilot CLI arguments. |
| `n_attempts` | Repetitions per agent/task cell. |
| `n_concurrent_trials` | Pier concurrency. |
| `artifacts` | Files or directories copied out of the environment after trials. |

## Workflow

```bash
uv run copilot-experiments run --dry-run
uv run copilot-experiments run
uv run copilot-experiments show --last
uv run copilot-experiments analyze --last --trial 1
```

If you are working from a standalone experiment repo and want to use a local checkout of the
`copilot-experiments` tool, replace `uv run copilot-experiments ...` with the form
`uvx --from <tool-repo> copilot-experiments ...`:

```bash
export COPILOT_EXPERIMENTS_REPO=/path/to/github-copilot-lab

uvx --from "$COPILOT_EXPERIMENTS_REPO" copilot-experiments run --dry-run
uvx --from "$COPILOT_EXPERIMENTS_REPO" copilot-experiments run
uvx --from "$COPILOT_EXPERIMENTS_REPO" copilot-experiments show --last
uvx --from "$COPILOT_EXPERIMENTS_REPO" copilot-experiments analyze --last --trial 1
```

In PowerShell, use
`$env:COPILOT_EXPERIMENTS_REPO = "C:\path\to\github-copilot-lab"` and pass
`--from $env:COPILOT_EXPERIMENTS_REPO`. If you are iterating on the tool and need to force uv to
rebuild from the working tree, add `--no-cache` before `--from`.

`--dry-run` validates Pier configs and path normalization without starting a sandbox. The legacy
Python experiment path still has an ephemeral mock dry-run, but Pier is the primary authoring
model.

Pier itself resumes existing matching job directories and skips trials that already have
`result.json`. `copilot-experiments run` treats a plain rerun as a fresh measurement instead: when
`jobs/<job_name>/` already exists, it appends a timestamp to the Pier job name for the new run. Pass
`--resume` to opt into Pier's native resume behavior for interrupted jobs.

## Legacy Python experiments

The old `Experiment`, `Task`, and `Variant` API remains temporarily for migration and tests. It is
used only when no Pier configs are found in `experiments/`. Do not use it for new experiment repos.
