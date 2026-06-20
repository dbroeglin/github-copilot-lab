# Tracer-bullet experiment

A small Pier-native task that exercises the Copilot CLI capture path end to end. The agent
must implement three functions in `tasks/textstats/environment/textstats.py` so the verifier
tests in `tasks/textstats/tests/test_textstats.py` pass.

## Run it

From the repository root:

```bash
# Validate the Pier JobConfig without starting a sandbox.
uv run copilot-experiments run --root examples/tracer_bullet --dry-run

# Real run through Pier. Requires Copilot auth and a supported Pier backend.
uv run copilot-experiments run     --root examples/tracer_bullet
uv run copilot-experiments analyze --root examples/tracer_bullet --last
uv run copilot-experiments show    --root examples/tracer_bullet --last
```

The job pins `gpt-5-mini` at `low` reasoning effort in
`experiments/textstats.yaml` so the smoke test stays inexpensive. Change that YAML to compare
models, efforts, or attempts.

Re-running the command creates a fresh timestamped job if `jobs/tracer-bullet-textstats/` already
exists. Use `--resume` only to continue an interrupted Pier job and intentionally skip completed
trials.

## What gets captured

Pier writes the first job under `jobs/tracer-bullet-textstats/` and subsequent reruns under
timestamped sibling directories. Each trial keeps Pier's `result.json`, verifier output, requested
artifacts, ATIF `trajectory.json`, raw Copilot CLI stdout/JSONL, and native Copilot
`copilot-session/**/events.jsonl` for AIU/token/session analysis.
