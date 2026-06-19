# 0014. SWE-bench as a task source with decoupled Docker grading

- **Status:** Accepted
- **Date:** 2026-06-18
- **Deciders:** project owner, Copilot

## Context

ADR-0012 made a task suite a first-class axis (`Tasks × Variants × Trials`) but
explicitly **deferred** the "option C" layer: an external dataset loader, patch-based
grading with `FAIL_TO_PASS` / `PASS_TO_PASS` semantics, and image-based provisioning. It
predicted those would be "the expected contents of a future option-C ADR that would build
on, not supersede, this one." This is that ADR.

The motivating goal is to reproduce the experimental protocol of Bai et al., *"How Do
Coding Agents Spend Your Money?"* (COLM 2026), but with **Copilot CLI as the agent**
instead of OpenHands. Their setup: run a population of **SWE-bench** instances, repeat each
**4 times** (HF tarballs are named `<model>_4runs.tar.gz`), use the bare problem statement
("no-hint"), and grade resolution with the official SWE-bench harness. The harness already
has everything needed to analyse the *results* — token economics (ADR-0011), cross-run
variance (CV), resolved@k / mean-success (ADR-0012), and the 5-phase trajectory split. What
was missing was (a) a way to turn SWE-bench instances into `Task`s and (b) ground-truth
grading.

Two forces shaped the design:

- **Grading is not a single exit code.** SWE-bench resolution is "did applying the model's
  patch make the `FAIL_TO_PASS` tests pass while `PASS_TO_PASS` still pass?", evaluated in a
  per-instance Linux container. The harness's existing per-trial `verify` (one shell command,
  binary pass/fail) cannot express this, and the official `swebench` evaluator already does it
  correctly. Reimplementing it would be wrong and unmaintainable.
- **The agent run and the grading run have different platform needs.** Copilot CLI runs
  host-native (Windows or Linux); the SWE-bench evaluator needs Docker with Linux containers.
  Coupling them would force the whole harness onto Linux/Docker.

## Decision

**We will add SWE-bench as a task _source_ plus a _separate_ batch grading stage, leaving the
result/reporting/index shapes from ADR-0012 unchanged.**

- A new library module `swebench.py` (not scaffolded-repo template code — it is harness
  functionality):
  - `load_instances` / `load_tasks` read instances from the Hugging Face dataset (optional
    `datasets` package) **or** a cached JSON/JSONL file, select a config-driven subset (explicit
    ids and/or first-N), and build `Task`s. The prompt is the bare `problem_statement`
    (no-hint); `repo` = `https://github.com/<repo>.git`, `ref` = `base_commit`.
  - SWE-bench metadata rides on the `Task` via a structured `SweBenchInstance` block
    (`instance_id`, `dataset`, `difficulty`, `FAIL_TO_PASS`, `PASS_TO_PASS`, …), persisted to
    `task.json`. `instance_id` and `difficulty` are threaded through `TaskResult` so the index
    and summary can group by them.
- **Grading is decoupled from the Copilot run.** Each trial's captured `workspace.diff`
  (ADR-0002) is the candidate `model_patch`. A separate stage, `grade_run`, exports one
  SWE-bench `predictions.jsonl` per `(variant, trial)` (so `instance_id`s stay unique within a
  file), runs an `Evaluator`, writes the resolved/unresolved verdict back into each trial
  (`meta.json` `success` + a `swebench.json`), then re-runs `build_summary` / `summary_markdown`
  and re-indexes. The existing per-trial `verify` is **not** used for SWE-bench grading.
- The `Evaluator` is a `Protocol`. The default `SwebenchDockerEvaluator` shells out to
  `python -m swebench.harness.run_evaluation` and parses `resolved_ids`; tests inject a stub.
  The `swebench` package and Docker are **optional** and only touched by the default evaluator —
  importing the module, loading from a cached file, the offline example, and the whole test
  suite work without them.
- Reporting gains a **difficulty-vs-cost** breakdown (group `(variant, task)` cells by
  SWE-bench `difficulty`), reproducing the paper's difficulty-alignment view. No new on-disk
  level is introduced — this rides on the ADR-0012 task layer.
- Two CLI commands: `swebench-init` (materialize a cached instance subset + a generated
  experiment file) and `swebench-eval` (run `grade_run` on a finished run).

## Consequences

- The harness can now run the Bai et al. protocol with Copilot CLI: a config-driven SWE-bench
  subset, repeated as `trials` (the paper's "runs"), graded with ground truth, analysed with
  the existing economics/variance/phase/difficulty lenses. It scales from a ~3-instance smoke
  set to Verified/500 × 4 by config alone.
- Grading is **out-of-band and re-runnable**. A run can be produced on a Windows host with no
  Docker, then graded later (or elsewhere) against a Docker engine; because the filesystem is
  the source of truth (ADR-0002) and the index is derived (ADR-0003), `grade_run` simply
  rewrites verdicts and re-aggregates. The verdict also lands in `meta.json`'s `success`, so it
  flows through the same `resolved@k` / mean-success / AIU-per-solve paths as `verify` results.
- New **optional** dependencies (`datasets`, `swebench` + Docker) are introduced as an extra.
  Core install, offline tests, and the committed example must never require them; the default
  evaluator fails with a clear, actionable message when they are absent.
- **Accepted limitations / deferred work.** v1 provisions a full clone per trial (no shallow
  clones or cached bare mirrors yet) and runs sequentially (no resumable/parallel execution),
  so pointing it at Verified/500 × 4 is expensive and crash-fragile — the same scale caveat
  ADR-0012 raised. The agent run is not sandboxed. `environment_setup_commit` is captured but
  the harness does not yet pre-build environment images. These are follow-ups that build on,
  not supersede, this decision.
