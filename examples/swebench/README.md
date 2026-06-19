# SWE-bench protocol example

Reproduce the experimental protocol of Bai et al., *"How Do Coding Agents Spend Your
Money?"* — but with **GitHub Copilot CLI as the agent** instead of OpenHands. Each
SWE-bench instance is one *task*; the experiment's `trials` axis is the paper's repeated
"runs" (they used 4). Resolution is graded by the **official `swebench` Docker harness**
against each instance's `FAIL_TO_PASS` / `PASS_TO_PASS` tests, and the harness's existing
token-economics, cross-run variance, and difficulty-vs-cost analyses do the rest.

This directory has two parts:

1. **A runnable offline demo** (`experiments/swebench_experiment.py`) that swaps real
   upstream repos for two tiny local fixtures so you can exercise the whole pipeline with
   **no network and no Docker**.
2. **A sample dataset file** (`swebench/instances.json`) showing the real SWE-bench
   instance schema that `copilot_experiments.swebench.load_tasks` consumes.

## 1. Offline demo (no network, no Docker)

```bash
# Validate the full pipeline with the mock invoker; nothing is persisted.
uv run copilot-experiments run  --root examples/swebench --dry-run

# A real run (needs an authenticated `copilot` on PATH and pytest available).
uv run copilot-experiments run  --root examples/swebench
uv run copilot-experiments show --root examples/swebench --last
```

The two demo "instances" carry SWE-bench metadata (`instance_id`, `difficulty`,
`FAIL_TO_PASS`, …) via `SweBenchInstance`, so `show` renders the **Difficulty vs cost**
table and the per-trial predictions-export path behaves exactly as it does for real
instances. The demo includes a `verify` command purely so it produces a success signal
without Docker — real SWE-bench runs omit `verify` and grade with `swebench-eval`.

## 2. The real protocol

### a. Materialize an experiment from the dataset

```bash
# Smoke set: first 3 SWE-bench Verified instances, one model, 2 trials each.
uv run copilot-experiments swebench-init my-swebench-run \
    --limit 3 --model claude-sonnet-4.5 --trials 2

# Or scale up to the paper's setup: a model matrix over Verified/500 × 4 runs.
uv run copilot-experiments swebench-init my-swebench-run \
    --dataset princeton-nlp/SWE-bench_Verified \
    --model claude-sonnet-4.5 --model gpt-5 --model gemini-3-pro \
    --trials 4
```

`swebench-init` downloads the selected subset (needs the optional `datasets` package),
caches it to `<dir>/swebench/instances.json` for reproducibility, and generates
`<dir>/experiments/swebench_experiment.py`. To stay fully offline, pass a pre-exported
`--instances-file path.json` (a JSON array or JSONL of instance dicts) instead of hitting
Hugging Face.

### b. Run Copilot on the instances (host-native)

```bash
uv run copilot-experiments run --root my-swebench-run
```

Each trial provisions a clean clone of the instance's repo at `base_commit`, runs Copilot
with the bare problem statement (the **no-hint** setup — the hidden test patch is never
revealed), and captures the resulting `workspace.diff` as the candidate `model_patch`.

### c. Grade resolution in Docker

```bash
uv run copilot-experiments swebench-eval --root my-swebench-run --last
```

`swebench-eval` exports one `predictions.jsonl` per (variant, trial), shells out to
`python -m swebench.harness.run_evaluation` (one Linux container per instance), reads back
each report's `resolved_ids`, writes the resolved/unresolved verdict into every trial, and
re-aggregates `summary.{json,md}` plus the SQLite index. After grading, `resolved@k`,
mean-success, and AIU-per-solve reflect ground-truth resolution.

## Prerequisites for real runs

- **`datasets`** (optional) — to download instances in `swebench-init`. Skip it by passing
  `--instances-file`.
- **`swebench`** (optional) + **Docker** — to grade with `swebench-eval`. The harness runs
  each instance in its own Linux container; start Docker Desktop or point `DOCKER_HOST` at a
  remote engine. Install with e.g. `uv pip install swebench datasets`.

Both are *optional*: importing the harness, running the offline demo, and the test suite all
work without them.

> **Note:** `swebench/instances.json` here is an illustrative sample of the real schema
> (two instance ids from SWE-bench). Regenerate a real subset with `swebench-init` before a
> live run. SWE-bench stores `FAIL_TO_PASS` / `PASS_TO_PASS` as JSON-encoded strings; the
> loader decodes both strings and native lists.
