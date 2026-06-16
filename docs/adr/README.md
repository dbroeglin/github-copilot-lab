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
| [0002](0002-filesystem-is-source-of-truth.md) | The filesystem is the source of truth | Accepted |
| [0003](0003-sqlite-derived-index.md) | A derived SQLite index for cross-run queries | Accepted |
| [0004](0004-session-log-is-primary-data-source.md) | The Copilot session log is the primary data source | Accepted |
| [0005](0005-mock-invoker-for-offline-tests.md) | A MockInvoker keeps the harness offline-testable | Accepted |
| [0006](0006-separate-analysis-data-from-rendering.md) | Separate analysis data from its rendering | Accepted |
| [0007](0007-cli-rich-analysis-before-web-app.md) | Ship CLI (Rich) analysis first; defer the web explorer | Accepted |
| [0008](0008-dry-run-is-ephemeral-plumbing-check.md) | `--dry-run` is an ephemeral, validating plumbing check | Accepted |
| [0009](0009-absolute-workspace-path-for-copilot.md) | Copilot is always invoked with an absolute workspace path | Accepted |
| [0010](0010-keep-secrets-and-debug-logs-out-of-results.md) | Keep secrets and bulky debug logs out of stored results | Accepted |
| [0011](0011-token-economics-from-session-shutdown.md) | Token economics from `session.shutdown` | Accepted |
| [0012](0012-auth-preflight-and-trial-diagnostics.md) | Auth preflight, harness-failure status, and richer trial diagnostics | Accepted |
