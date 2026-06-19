# SWE-bench

The Pier refactor changes the target shape for SWE-bench support: SWE-bench instances should
materialize as Pier task directories, and grading should be expressed as Pier verifier/artifact
collection where practical.

## Current state

- `examples/swebench` contains two local SWE-bench-shaped Pier tasks.
- Each task stores metadata such as `instance_id`, `difficulty`, `fail_to_pass`, and
  `pass_to_pass` in `task.toml`.
- `copilot-experiments run` executes those tasks through Pier and the local `copilot-cli` agent.
- `copilot-experiments swebench-eval` can grade either legacy runs or Pier jobs. For Pier jobs,
  it derives each `model_patch` from the captured `artifacts/repo` git checkout, writes the
  verdict back into the trial `result.json`, and regenerates `summary.json` / `summary.md`.

## Desired real-protocol flow

```bash
uv run copilot-experiments swebench-init my-swebench-run \
    --dataset princeton-nlp/SWE-bench_Verified \
    --limit 3 \
    --model gpt-5-mini \
    --trials 2

uv run copilot-experiments run --root my-swebench-run
uv run copilot-experiments show --root my-swebench-run --last
uv run copilot-experiments swebench-eval --root my-swebench-run --last
```

The Pier-native `swebench-init` should:

1. load/cache selected SWE-bench instances;
2. create one `tasks/<instance-id>/` directory per instance;
3. build each environment at the instance base commit;
4. write `instruction.md` from the no-hint problem statement;
5. configure verifier/artifact scripts to capture patches and resolution signals;
6. write Pier `experiments/*.yaml` with `n_attempts` matching the repeated-run protocol.

## Why Pier owns this

SWE-bench is fundamentally sandbox/verifier/artifact orchestration. Pier already has the right
abstractions for task environments, installed agents, verifier rewards, concurrency, and output
layout. `copilot-experiments` should contribute Copilot-native telemetry and reporting rather than
reimplementing that substrate.
