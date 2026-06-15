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

The real run is deliberately **cheap**: it pins one of the cheapest Copilot models
(`gpt-5-mini`) at `low` reasoning effort rather than inheriting your (possibly expensive)
account default. Change the `DEFAULT_MODEL` / `DEFAULT_EFFORT` constants at the top of
[`experiments/textstats_experiment.py`](experiments/textstats_experiment.py) to try a
different model (e.g. `claude-haiku-4.5`), or set `DEFAULT_MODEL = None` to use whatever
model your CLI is configured with. A typical run solves the task in well under a minute of
model time for a few AIU — the `analyze` view then shows exactly where those credits went.

> Note: with a reasoning model like `gpt-5-mini`, the `analyze` timeline's "assistant said"
> column is blank on most turns — the model goes straight to a tool call without narrating, and
> keeps its reasoning encrypted. That is expected and does not affect any metric; the `tools`
> column still shows what each turn did. See [`docs/analysis.md`](../../docs/analysis.md).

## What gets captured

Each trial writes a self-describing folder under `results/` (git-ignored), including the
copied `events.jsonl` session log, parsed `metrics.json`, and the richer `analysis.json`.
See [`docs/results-format.md`](../../docs/results-format.md) and
[`docs/analysis.md`](../../docs/analysis.md).
