# Running DeepSWE tasks

DeepSWE is already a Harbor/Pier task corpus, so `copilot-experiments` does not need to
translate task data or reimplement a benchmark runner. The integration point is a Pier
`JobConfig` that points at a cloned DeepSWE checkout and uses this package's `copilot-cli`
installed agent.

DeepSWE task directories contain:

```text
task.toml         task metadata, repository/base commit, Docker image, limits
instruction.md    prompt shown to the agent
pre_artifacts.sh  captures the agent's committed work as /logs/artifacts/model.patch
environment/      Dockerfile for the agent workspace image
tests/            separate verifier environment, held-out tests, grader config
solution/         reference solution; not used during grading
```

Since DeepSWE v1.1 uses Pier's separate verifier environment, keep `datacurve-pier>=0.3.0`
installed and run through Pier-backed `copilot-experiments` jobs.

## Import a DeepSWE checkout

Clone DeepSWE next to, or inside, your experiment repository:

```bash
git clone https://github.com/datacurve-ai/deep-swe vendor/deep-swe
```

Generate a Pier job config:

```bash
uv run copilot-experiments deepswe-import vendor/deep-swe \
  --job-name deepswe-smoke \
  --model gpt-5-mini \
  --effort medium \
  --n-tasks 3 \
  --sample-seed 0
```

This writes `experiments/deepswe-smoke.yaml`:

```yaml
job_name: deepswe-smoke
jobs_dir: jobs
n_attempts: 1
n_concurrent_trials: 1
agents:
  - name: copilot-cli
    model_name: gpt-5-mini
    kwargs:
      reasoning_effort: medium
datasets:
  - path: ../vendor/deep-swe/tasks
    n_tasks: 3
    sample_seed: 0
```

Validate and run it like any other Pier experiment:

```bash
uv run copilot-experiments validate
uv run copilot-experiments run deepswe-smoke
uv run copilot-experiments list
uv run copilot-experiments show --last
uv run copilot-experiments inspect --last
uv run copilot-experiments analyze --last --agent copilot-cli --trial 1
```

## Selecting tasks

The importer accepts a DeepSWE checkout root, a `tasks/` directory, or a single task directory.

Use Pier dataset filters for repeatable subsets:

```bash
uv run copilot-experiments deepswe-import vendor/deep-swe/tasks \
  --job-name deepswe-typescript \
  --task "datacurve/*" \
  --n-tasks 10 \
  --sample-seed 42
```

For one task:

```bash
uv run copilot-experiments deepswe-import vendor/deep-swe/tasks/abs-stepped-slices \
  --job-name deepswe-abs-stepped-slices
```

Single-task imports emit a `tasks:` entry; corpus imports emit a `datasets:` entry so Pier can
filter, sample, and expand the corpus at run time.

## Scaling notes

DeepSWE currently contains long-horizon tasks with large timeouts and resource budgets. Start with
`--n-tasks` and `--n-attempts 1`, then increase attempts and concurrency once the backend is stable.
Use `--environment modal` if your Pier setup runs DeepSWE on Modal; otherwise omit it and use Pier's
default backend.

The generated config can be edited directly:

- `n_attempts` controls repeated trials per task/model cell.
- `n_concurrent_trials` controls Pier concurrency.
- `agents[]` can contain multiple `copilot-cli` model/effort rows.
- `datasets[].task_names`, `n_tasks`, and `sample_seed` control corpus selection.

## Results and boundaries

Pier performs DeepSWE grading through each task's verifier and writes `reward.json`, `ctrf.json`,
raw verifier logs, and artifacts such as `model.patch`. `copilot-experiments` then derives
`summary.json`, `summary.md`, the SQLite index, and Copilot-native session analysis from the Pier
job directory.

The importer deliberately does not:

- clone DeepSWE for you;
- copy or rewrite task directories;
- read or expose `solution/` as part of a run;
- implement a separate SWE-bench-style grading phase;
- add DeepSWE-specific difficulty or leaderboard reporting to the core summary path.

Those boundaries keep this project aligned with its Pier-first architecture: Pier owns sandboxed
execution and benchmark grading; `copilot-experiments` owns Copilot CLI invocation, session capture,
and reusable result analysis.
