---
description: How to work in a copilot-experiments repository.
applyTo: "**"
---

# Working in this experiment repository

- Experiments are Pier `JobConfig` YAML files in `experiments/*.yaml`.
- Tasks live under `tasks/<name>/` as Harbor/Pier task directories.
- Generated Pier job data lives under `jobs/` and must not be edited by hand.

When adding an experiment:
1. Create a deterministic task directory under `tasks/`.
2. Write `instruction.md`, `task.toml`, `environment/`, and `tests/test.sh`.
3. Define or update a Pier job YAML in `experiments/`.
4. Use the local Copilot agent import path:
   `copilot_experiments.pier_agents.copilot_cli:CopilotCli`.
5. Validate configs with `copilot-experiments validate` before a real run.
