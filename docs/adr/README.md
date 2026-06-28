# Architecture Decision Records

This log captures the **why** behind `copilot-experiments`' design. Each ADR is a short,
immutable record of one decision: its context, the decision itself, and the consequences.
We follow the lightweight format popularized by
[Michael Nygard](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).

## Conventions

- One file per decision, numbered sequentially: `NNNN-short-title.md`.
- **Status:** `Proposed` → `Accepted` → (later) `Superseded by ADR-XXXX` / `Deprecated`.
- ADRs are append-only. To change a decision, add a new ADR that supersedes the old one
  (and update the old one's status); don't rewrite history.
- Use [`0000-template.md`](0000-template.md) as the starting point.

## Index

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-filesystem-is-source-of-truth.md) | The filesystem is the source of truth | Accepted; amended by ADR-0015 |
| [0003](0003-sqlite-derived-index.md) | A derived SQLite index for cross-run queries | Superseded by ADR-0020 |
| [0004](0004-session-log-is-primary-data-source.md) | The Copilot session log is the primary data source | Accepted |
| [0005](0005-mock-invoker-for-offline-tests.md) | A MockInvoker keeps the harness offline-testable | Superseded by ADR-0015 for Pier runs |
| [0006](0006-separate-analysis-data-from-rendering.md) | Separate analysis data from its rendering | Accepted |
| [0007](0007-cli-rich-analysis-before-web-app.md) | Ship CLI (Rich) analysis first; defer the web explorer | Accepted |
| [0008](0008-dry-run-is-ephemeral-plumbing-check.md) | `--dry-run` is an ephemeral, validating plumbing check | Superseded by ADR-0015 for Pier runs |
| [0009](0009-absolute-workspace-path-for-copilot.md) | Copilot is always invoked with an absolute workspace path | Superseded by ADR-0015 for Pier runs |
| [0010](0010-keep-secrets-and-debug-logs-out-of-results.md) | Keep secrets and bulky debug logs out of stored results | Accepted |
| [0011](0011-token-economics-from-session-shutdown.md) | Token economics from `session.shutdown`, costed in AIU | Accepted |
| [0012](0012-task-suite-as-experiment-axis.md) | A task suite is an axis of an experiment | Superseded by ADR-0015 |
| [0013](0013-auth-preflight-and-trial-diagnostics.md) | Auth preflight, harness-failure status, and richer trial diagnostics | Accepted |
| [0014](0014-swebench-task-source-and-docker-grading.md) | SWE-bench as a task source with decoupled Docker grading | Superseded by ADR-0016 |
| [0015](0015-adopt-pier-for-sandboxed-agent-evals.md) | Adopt Pier for sandboxed agent evaluations | Accepted |
| [0016](0016-use-deepswe-for-large-benchmark-protocols.md) | Use DeepSWE for large benchmark protocols | Accepted |
| [0017](0017-import-deepswe-as-pier-dataset.md) | Import DeepSWE as a Pier dataset config | Accepted |
| [0018](0018-adopt-pytest-cov-for-local-coverage-analysis.md) | Adopt pytest-cov for local coverage analysis | Accepted |
| [0019](0019-use-nested-pier-run-directories.md) | Use nested Pier run directories | Accepted |
| [0020](0020-remove-legacy-native-harness.md) | Remove the legacy native harness | Accepted |
