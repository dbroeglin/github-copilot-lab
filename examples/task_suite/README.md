# Task-suite example

A Pier-native job that runs one cheap Copilot agent across two tasks of different
difficulty:

| Task | Directory | Difficulty | What the model must do |
| ---- | --------- | ---------- | ---------------------- |
| Reverse words | `tasks/reverse-words` | easy | implement one string helper |
| CSV parser | `tasks/csv-parser` | medium | implement an RFC 4180-style parser |

## Run it

From the repository root:

```bash
uv run copilot-experiments validate --root examples/task_suite
uv run copilot-experiments run  --root examples/task_suite
uv run copilot-experiments show --root examples/task_suite --last
```

The job config is `experiments/suite.yaml`. It pins `gpt-5-mini` at `low` effort and sets
`n_attempts: 1`; edit the YAML to compare models, attempts, or concurrency.

## What to expect

Pier writes concrete executions under `jobs/task-suite-strtools-csvtools/<run-id>/`, with a
trial directory for every `agent x task x attempt` cell. `copilot-experiments show` derives an
agent/task summary, while `analyze` reads the native Copilot `events.jsonl` from a selected trial.
