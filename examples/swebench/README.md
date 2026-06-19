# SWE-bench protocol example

This directory now demonstrates the Pier/Harbor shape for SWE-bench-like tasks with two tiny
local fixtures:

| Task | Directory | Difficulty |
| ---- | --------- | ---------- |
| `demo__textnorm-1` | `tasks/textnorm-easy` | easy |
| `demo__romans-1` | `tasks/romans-hard` | hard |

Each task carries SWE-bench-style metadata in `task.toml` (`instance_id`, `difficulty`,
`fail_to_pass`, `pass_to_pass`) and uses a Pier verifier script to produce a reward.

## Offline demo

```bash
uv run copilot-experiments run  --root examples/swebench --dry-run
uv run copilot-experiments run  --root examples/swebench
uv run copilot-experiments show --root examples/swebench --last
```

The real run goes through Pier and the local `copilot-cli` installed agent. `n_attempts: 2`
in `experiments/offline-demo.yaml` mirrors the repeated-run shape used by SWE-bench studies.

## Real SWE-bench direction

`swebench/instances.json` remains as a sample of the upstream instance schema. The next
iteration of `swebench-init` should materialize each selected instance as a Pier task directory
and express grading as Pier verifier/artifact collection rather than the legacy host-side
Python `Experiment` model.
