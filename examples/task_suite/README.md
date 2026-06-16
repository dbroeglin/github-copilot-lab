# Task-suite example

A committed, runnable example of the **task axis** ([ADR-0012](../../docs/adr/0012-task-suite-as-experiment-axis.md)):
an experiment is `Tasks x Variants x Trials`. One cheap variant runs **two independent
tasks of different difficulty**, so the run exercises the suite-coverage metrics that only
appear when an experiment has more than one task.

| Task | Fixture | Difficulty | What the model must do |
| ---- | ------- | ---------- | ---------------------- |
| Reverse words | [`fixtures/strtools`](fixtures/strtools/strtools.py) | trivial | implement one function (`reverse_words`) |
| CSV parser | [`fixtures/csvtools`](fixtures/csvtools/csvtools.py) | harder | implement an RFC 4180-style `parse_csv` with a small quoting state machine |

Each task ships a stub that raises `NotImplementedError` plus a `test_*.py` file that is the
exact behavioral spec. The model reads the tests, implements the code, and runs the suite.

## Run it

From the repository root:

```bash
# Dry-run: mock Copilot, no credits. Creates a tasks/<slug>/ directory per task.
uv run copilot-experiments run  --root examples/task_suite --dry-run

# See the per-variant table with the suite-coverage columns.
uv run copilot-experiments show --root examples/task_suite --last
```

For a **real** run you need an authenticated `copilot` on your `PATH` and `pytest` available
to the `python` that runs the `verify` command:

```bash
uv run copilot-experiments run     --root examples/task_suite
uv run copilot-experiments inspect --root examples/task_suite --last            # list variants -> tasks -> trials
uv run copilot-experiments inspect --root examples/task_suite --last --variant default --task csv-parser
```

Like the tracer-bullet example, the real run is deliberately cheap: it pins `gpt-5-mini` at
`low` effort. Change `DEFAULT_MODEL` / `DEFAULT_EFFORT` at the top of
[`experiments/suite_experiment.py`](experiments/suite_experiment.py) to compare other models,
or set `DEFAULT_MODEL = None` to inherit your CLI default.

## What to expect

The results nest one level deeper than a single-task experiment:

```
results/<run-id>/variants/default/tasks/reverse-words/trials/001/...
results/<run-id>/variants/default/tasks/csv-parser/trials/001/...
```

The summary adds two suite-coverage numbers per variant:

* **mean-success** -- mean over tasks of each task's mean trial success.
* **resolved@k** -- fraction of tasks where any trial passed.

With a cheap model the easy task usually passes while the harder CSV parser may not, so
`resolved@k` is a good way to see coverage drop on the difficult task. See
[`docs/results-format.md`](../../docs/results-format.md) for the full layout and
[`docs/authoring-experiments.md`](../../docs/authoring-experiments.md) for the task-suite API.
