---
description: Scaffold a new experiment from a short description.
---

# New experiment

Create a new GitHub Copilot experiment in this repository.

Given a task description from the user:
1. Create a deterministic Harbor/Pier task under `tasks/<slug>/` with `task.toml`,
   `instruction.md`, `environment/`, and `tests/test.sh`.
2. Add `experiments/<slug>.yaml` defining a Pier `JobConfig` with the `copilot-cli` agent, model
   settings, attempts, and artifacts.
3. Validate with `copilot-experiments validate` and fix any errors.

Ask for the model matrix and number of attempts if not provided.
