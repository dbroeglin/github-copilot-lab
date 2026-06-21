---
name: authoring-experiments
description: >-
  Use when creating or editing a GitHub Copilot experiment in this repository:
  defining Harbor/Pier task directories and Pier JobConfig YAML.
---

# Authoring experiments

A task is a Harbor/Pier task directory. An experiment is a Pier JobConfig YAML file that combines
tasks, agents, models, and attempts.

## Task
- `instruction.md` — the instruction handed to the agent.
- `task.toml` — task metadata, environment, verifier, and artifacts.
- `environment/` — Dockerfile or other environment definition.
- `tests/test.sh` — verifier script. It should write `1` or `0` to `/logs/verifier/reward.txt`.
- `solution/solve.sh` — optional oracle/reference solution.

## Job config

```yaml
job_name: my-task
jobs_dir: jobs
n_attempts: 3
n_concurrent_trials: 2
agents:
  - import_path: copilot_experiments.pier_agents.copilot_cli:CopilotCli
    model_name: claude-opus-4.7
    kwargs:
      reasoning_effort: medium
tasks:
  - path: ../tasks/my-task
```

Use more `agents` rows for model/agent comparisons and more `tasks` rows or `datasets` for
suites.

For DeepSWE, do not rewrite tasks. Clone `datacurve-ai/deep-swe` and generate a Pier dataset job:

```bash
copilot-experiments deepswe-import vendor/deep-swe --n-tasks 3 --sample-seed 0
```

## Validate
```bash
copilot-experiments run --dry-run   # validates configs, no credits
```
