# 0008. `--dry-run` is an ephemeral, validating plumbing check

- **Status:** Superseded by [ADR-0015](0015-adopt-pier-for-sandboxed-agent-evals.md) for Pier runs
- **Date:** 2026-06-15
- **Deciders:** project owner, Copilot

> **Amendment (ADR-0015):** this remains true for legacy Python experiments. Pier-native
> `--dry-run` validates Pier job configs without running a sandbox; Pier execution smoke tests
> should use explicit optional integration tests.

## Context

ADR-0005 introduced `--dry-run` as "use the mock invoker so the pipeline runs offline." In
practice it did two things we came to regret:

1. **It persisted a full run.** A dry-run wrote a complete `results/<run-id>/` tree, mutated
   `index.db`, and emitted `summary.json`/`summary.md` — indistinguishable on disk from a real
   run, just with synthetic data. Users then had to manually prune "fake" runs, and aggregate
   reports risked mixing real and mock data.
2. **It reported success without checking anything.** A Windows `MAX_PATH` bug left
   `workspace.diff` empty while the dry-run still printed a green summary. The one job a
   smoke test has — catching broken plumbing — it did not do, because it never *inspected*
   the artifacts it produced.

The user's guidance was explicit: a dry-run "should not leave anything behind," and the
synthetic results are not worth keeping.

## Decision

We will redefine `--dry-run` as an **ephemeral, validating plumbing check**, modelled on
`terraform plan` / `rsync -n`:

- `dry_run_experiment()` runs the entire pipeline with the `MockInvoker` inside a throwaway
  `tempfile.mkdtemp()` directory (`results_root` and `session_state_root` both point there).
  Fixtures and experiment definitions are still read from the real `root`; only *outputs* are
  redirected.
- After the run, `_validate_plumbing()` **inspects the on-disk artifacts** and produces a
  `DryRunReport` of pass/fail checks: workspace provisioned with a git baseline, session log
  captured and parseable, metrics parsed (≥1 turn), analysis written, **`workspace.diff`
  non-empty**, verification ran, run summary written, and the run is present in the index.
- The temp directory is then deleted with a Windows-robust `force_rmtree()` (long-path prefix +
  read-only retry) in a `finally`. **Nothing is persisted under the experiment repo.**
- The CLI renders the checklist and exits non-zero if any check fails.

Consequently we **remove the `dry_run` parameter from `run_experiment()`** and drop the ability
to persist a mock run from the CLI. `run_experiment(invoker=MockInvoker())` remains available as
a library/test entry point for code that genuinely needs persisted synthetic artifacts (the test
suite uses it); there is simply no user-facing flag that leaves mock data behind.

## Consequences

- A dry-run now answers the question it always should have — "is every stage wired up and
  producing real output on this machine?" — and would have caught the `MAX_PATH` regression
  (the non-empty-diff check fails when the invoker's changes are silently lost).
- `results/` only ever contains real runs, so aggregation and the future web explorer never see
  synthetic data, and there is no "clean up the fake runs" chore.
- There is no longer a CLI path to keep mock output. If a persisted mock run is ever needed
  again (e.g. for a demo fixture), it must go through the library API or a committed example,
  not `--dry-run`.
- `Layout` gained a `results_root` override (write location decoupled from `root`), which is
  also a useful seam for future "run against repo X, write results to Y" scenarios.
- This **amends ADR-0005**: the mock invoker still underpins offline testing, but the claims
  that "`--dry-run` is a faithful smoke test" and "dry-runs produce meaningful analyses" are
  superseded here — dry-run analyses are now validated and then discarded, not retained.
