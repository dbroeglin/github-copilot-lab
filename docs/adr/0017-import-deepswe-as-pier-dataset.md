# 0017. Import DeepSWE as a Pier dataset config

- **Status:** Accepted
- **Date:** 2026-06-21
- **Deciders:** project owner, Copilot

## Context

ADR-0016 chose DeepSWE as the path for large SWE-style benchmark protocols and removed in-tree
SWE-bench-specific loading, grading, and reporting. DeepSWE itself is already a Harbor/Pier task
corpus: each task has `task.toml`, `instruction.md`, `pre_artifacts.sh`, `environment/`, `tests/`,
and a held-out `solution/`.

Users still need a bridge from a cloned DeepSWE checkout to this package's Pier-first experiment
repository shape. `copilot-experiments run` discovers Pier `JobConfig` files under `experiments/`;
DeepSWE's quickstart uses `pier run -p deep-swe/tasks` directly.

## Decision

Add a lightweight `deepswe-import` command and library helper that generate a Pier `JobConfig` YAML
file pointing at DeepSWE tasks.

- A DeepSWE checkout root or `tasks/` corpus becomes a `datasets:` entry so Pier can expand, filter,
  and sample task directories.
- A single DeepSWE task directory becomes a `tasks:` entry.
- The importer validates only the task-directory shape needed to avoid obvious misconfiguration.
- The generated config uses the local `copilot-cli` Pier installed agent and standard JobConfig
  fields for model, effort, attempts, concurrency, environment backend, and dataset sampling.

## Consequences

- Users can run DeepSWE through `copilot-experiments` without copying tasks or authoring YAML by
  hand, while preserving DeepSWE/Pier as the benchmark execution and grading layer.
- The package does not grow a DeepSWE-specific runner, grader, leaderboard, task converter, or result
  schema. Summaries and indexes remain generic Pier job/session analysis.
- The importer is safe to test offline because it writes YAML and validates local paths only; it does
  not clone repositories, pull Docker images, run Copilot, or call Pier execution APIs.
