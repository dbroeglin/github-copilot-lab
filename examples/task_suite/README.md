# Task-suite example

A Pier-native job that runs one cheap Copilot variant across two tasks of different
difficulty:

| Task | Directory | Difficulty | What the model must do |
| ---- | --------- | ---------- | ---------------------- |
| Reverse words | `tasks/reverse-words` | easy | implement one string helper |
| CSV parser | `tasks/csv-parser` | medium | implement an RFC 4180-style parser |

## Run it

From the repository root:

```bash
uv run copilot-experiments run  --root examples/task_suite --dry-run
uv run copilot-experiments run  --root examples/task_suite
uv run copilot-experiments show --root examples/task_suite --last
```

The job config is `experiments/suite.yaml`. It pins `gpt-5-mini` at `low` effort and sets
`n_attempts: 1`; edit the YAML to compare models, attempts, or concurrency.

## What to expect

Pier writes one canonical job directory under `jobs/task-suite-strtools-csvtools/`, with a
trial directory for every `agent x task x attempt` cell. `copilot-experiments show` adapts
those Pier outputs into the familiar per-variant/per-task summary, while `analyze` reads the
native Copilot `events.jsonl` from a selected trial.
