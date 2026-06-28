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

## DeepSWE task corpora

DeepSWE tasks already use the Harbor/Pier task format, including separate verifier environments.
Generate a Pier job config that points at the DeepSWE checkout:

```bash
git clone https://github.com/datacurve-ai/deep-swe vendor/deep-swe
uv run copilot-experiments deepswe-import vendor/deep-swe \
  --job-name deepswe-smoke \
  --model gpt-5-mini \
  --n-tasks 3 \
  --sample-seed 0
```

The generated config uses `datasets:` for a corpus and `tasks:` for a single task directory. See
[`deepswe.md`](deepswe.md) for task selection, scaling, and result-analysis notes.

## Workflow

```bash
uv run copilot-experiments validate
uv run copilot-experiments run
uv run copilot-experiments list
uv run copilot-experiments show --last
uv run copilot-experiments inspect --last
uv run copilot-experiments analyze --last --agent copilot-cli --trial 1
```

If you are working from a standalone experiment repo and want to use a local checkout of the
`copilot-experiments` tool, replace `uv run copilot-experiments ...` with the form
`uvx --from <tool-repo> copilot-experiments ...`:

```bash
export COPILOT_EXPERIMENTS_REPO=/path/to/github-copilot-lab

uvx --from "$COPILOT_EXPERIMENTS_REPO" copilot-experiments validate
uvx --from "$COPILOT_EXPERIMENTS_REPO" copilot-experiments run
uvx --from "$COPILOT_EXPERIMENTS_REPO" copilot-experiments list
uvx --from "$COPILOT_EXPERIMENTS_REPO" copilot-experiments show --last
uvx --from "$COPILOT_EXPERIMENTS_REPO" copilot-experiments analyze --last --agent copilot-cli --trial 1
```

In PowerShell, use
`$env:COPILOT_EXPERIMENTS_REPO = "C:\path\to\github-copilot-lab"` and pass
`--from $env:COPILOT_EXPERIMENTS_REPO`. If you are iterating on the tool and need to force uv to
rebuild from the working tree, add `--no-cache` before `--from`.

`validate` checks Pier config loading, referenced task/dataset paths, backend availability, and
Copilot auth without creating a run directory.

`run` performs a lightweight backend preflight before Pier creates a job. For the default Docker
backend it verifies that `docker`, `docker compose`, and the Docker daemon are reachable; this catches
common WSL/Docker Desktop integration issues before a trial can fail without Copilot logs.

Pier itself resumes existing matching job directories and skips trials that already have
`result.json`. `copilot-experiments run` treats a plain rerun as a fresh measurement instead: when
the configured `job_name` is used as a stable grouping directory and each execution gets a
timestamped run id under `jobs/<job_name>/<run-id>/`. Pass `--resume` to reuse the latest existing
run directory for that job and opt into Pier's native skip-completed-trials behavior.

After a run, `copilot-experiments list` prints copyable selectors. Use `job-name/run-id` to inspect
or analyze an exact Pier execution, `job-name` for that job's latest run, or `--last` for the most
recent stored run across all jobs.

`run` always executes Pier jobs. Native Python `Experiment`/`Task`/`Variant` experiments are no
longer supported by the CLI.
