---
description: Scaffold a new experiment from a short description.
---

# New experiment

Create a new GitHub Copilot experiment in this repository.

Given a task description from the user:
1. Create a deterministic, self-contained fixture under `fixtures/<slug>/`.
2. Add `experiments/<slug>.py` defining an `Experiment` with a `Task`
   (prompt + `fixture` + a strict `verify` command) and a small matrix of `Variant`s.
3. Validate with `copilot-experiments run --dry-run` and fix any errors.

Ask for the model matrix and number of trials if not provided.
