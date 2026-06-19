# 0012. A task suite is an axis of an experiment

- **Status:** Superseded by [ADR-0015](0015-adopt-pier-for-sandboxed-agent-evals.md)
- **Date:** 2026-06-16
- **Deciders:** project owner, Copilot

> **Amendment (ADR-0015):** Pier's `agents x tasks x n_attempts` job model is now the primary
> matrix. The Python `Experiment = Tasks x Variants x Trials` model remains a legacy bridge.

## Context

An `Experiment` today is one `Task` crossed with a list of `Variant`s, each repeated
`trials` times: `Experiment = 1 Task × N Variants × T Trials`. The matrix axis is the
**variant** (model / effort / provider / tools); the task is fixed. Aggregation in
[`report.py`](../../src/copilot_experiments/report.py) reflects this — a variant's
`success_rate`, `cv_aiu`, and `cv_total_tokens` are all computed across the repeated
trials of *the same single task*. That is the right unit for the question the harness
was built around (per ADR-0011 and the Bai et al. token-economics paper): **for one
task, how do models compare on cost, reliability, and context dynamics, and how variable
is that across repeated runs?**

It is the wrong unit for a second, equally legitimate question: **capability coverage**.
Benchmarks like SWE-bench (2294 instances) and DeepSWE report *"% resolved over a task
population"*. A single task yields a reliability estimate at one point; it cannot estimate
a distribution over a population of tasks. To compare models the way those benchmarks do,
a task **suite** must be a first-class axis, not something faked by running many separate
one-task experiments and stitching their summaries together after the fact.

Three shapes were considered:

- **A. Many one-task experiments, aggregated at report time.** No model change, but there
  is no first-class "suite" — a per-model resolved-rate over a suite has to be reconstructed
  by a cross-experiment aggregator that does not exist, and the suite has no identity, no
  shared run id, and no single summary.
- **B. `tasks: list[Task]` on `Experiment`.** The experiment becomes
  `Tasks × Variants × Trials`. Tasks are defined inline (or imported) in the same Python
  experiment file. Curated suites of tens of tasks fit naturally; the existing `Task` model
  (`repo` + `ref` + `setup` + `verify`) already maps loosely onto a benchmark instance.
- **C. A `Suite` / `Benchmark` concept above `Experiment`,** with tasks streamed from an
  external manifest/dataset (e.g. the SWE-bench instance set). Needed only at the
  hundreds-to-thousands scale, and it brings its own hard problems — resumability,
  parallelism, image-based provisioning, and patch-based grading (`FAIL_TO_PASS` /
  `PASS_TO_PASS`) that a single exit-code `verify` does not express.

## Decision

**We will adopt option B now and keep option C open as a later, additive layer.**

- `Experiment` gains `tasks: list[Task]`. An experiment runs the full cross product
  `Tasks × Variants × Trials`. For backwards compatibility the existing singular `task`
  field is retained as sugar for a one-element suite (a `task=...` experiment behaves
  exactly as before).
- Each task gets a stable `slug` (mirroring `Variant.slug`) so it can name a directory and
  an index dimension.
- The on-disk layout (ADR-0002, the source of truth) gains a **task** level between variant
  and trials:

  ```
  <run-id>/variants/<variant-slug>/tasks/<task-slug>/trials/<NNN>/...
  ```

  A single-task experiment still produces exactly one `tasks/<slug>/` directory, so the
  layout is uniform rather than conditionally nested.
- Reporting aggregates at **two** levels: the existing per-`(variant, task)` cell (cost and
  cross-trial variability, unchanged in meaning), **and** a new per-variant roll-up **over
  the suite** — the benchmark-style **resolved rate** (fraction of tasks solved), plus a
  per-task breakdown so a model that is cheap-on-average but fails a hard cluster is visible.
- The derived SQLite index (ADR-0003) grows a `task_slug` column on `trials`; because the DB
  is rebuildable, `reindex` recreates it with no migration.
- **We will not** build the `Suite`/dataset loader, parallel/resumable execution, or
  patch-based grading as part of this decision. Those are the load-bearing pieces of option C
  and are deferred until a real large-benchmark need exists. B is designed so that C can be
  introduced as a task *source* (something that produces a `list[Task]`) without reshaping
  results, reporting, or the index again.

## Consequences

- The harness can compare models on a curated suite (resolved %) *and* keep the
  token-economics/variability lens per task — the two research questions coexist under one
  run with one summary.
- Result paths get one level deeper. Tooling that walks `variants/<slug>/trials/...` must
  learn the `tasks/<slug>/` level; `storage.Layout`, the runner's trial loop, `index`, and
  `report` all change. The dry-run plumbing check (ADR-0008) and `MockInvoker` (ADR-0005)
  must exercise a ≥2-task suite so the new axis is covered offline.
- Run cost scales as `tasks × variants × trials`. A curated suite of tens of tasks is fine;
  this is *not* a license to point B at thousands of instances — at that scale the deferred
  option-C concerns (resumability, parallelism, sampling, cost control) become mandatory, and
  running a giant suite under the current sequential, one-shot runner would risk losing hours
  of work to a single crash.
- **Accepted limitations.** Grading stays single-command `verify` (binary pass/fail); we are
  not adopting SWE-bench's `FAIL_TO_PASS` / `PASS_TO_PASS` test-set semantics or image-based
  provisioning here. Those, the external dataset loader, and parallel execution are the
  expected contents of a future option-C ADR that would build on, not supersede, this one.
