# Tracer-bullet experiment

A committed, runnable example that exercises the **whole** `copilot-experiments` pipeline
end to end: provision an isolated workspace → drive the Copilot CLI → capture the session
log → parse metrics → run the **session-log analysis** → render it in the terminal.

The task is small but **multi-turn**: implement three functions in
[`fixtures/textstats/textstats.py`](fixtures/textstats/textstats.py) so the tests in
`test_textstats.py` pass. A model has to read the tests, implement each function, run the
suite, and fix anything that fails — several assistant turns.

## Run it

From the repository root:

```bash
# Dry-run: mock Copilot, no credits. Writes a synthetic, multi-turn session log so the
# analysis has something realistic to chew on.
uv run copilot-experiments run     --root examples/tracer_bullet --dry-run

# Analyze the most recent run's captured session log and render an overview.
uv run copilot-experiments analyze --root examples/tracer_bullet --last
```

For a **real** run you need an authenticated `copilot` on your `PATH`, and `pytest`
available to the `python` that runs the `verify` command:

```bash
uv run copilot-experiments run     --root examples/tracer_bullet
uv run copilot-experiments analyze --root examples/tracer_bullet --last
uv run copilot-experiments show    --root examples/tracer_bullet --last
```

## What gets captured

Each trial writes a self-describing folder under `results/` (git-ignored), including the
copied `events.jsonl` session log, parsed `metrics.json`, and the richer `analysis.json`.
See [`docs/results-format.md`](../../docs/results-format.md) and
[`docs/analysis.md`](../../docs/analysis.md).
