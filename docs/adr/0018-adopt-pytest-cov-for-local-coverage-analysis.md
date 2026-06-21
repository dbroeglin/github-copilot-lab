# 0018. Adopt pytest-cov for local coverage analysis

- **Status:** Accepted
- **Date:** 2026-06-21
- **Deciders:** project owner, Copilot

## Context

The package already uses pytest for an offline test suite, Ruff for formatting and linting, uv for
dependency management, and GitHub Actions for quality checks. The project has no existing coverage
configuration, dependency, reporting command, or CI coverage checkpoint.

Coverage analysis should stay local and GitHub Actions-only. A hosted service would add account,
permission, badge, and upload concerns that are not needed for the current workflow. The chosen tool
should also feel lightweight and current rather than adding a separate clunky reporting system.

## Decision

We will use `pytest-cov` as the pytest integration layer for `coverage.py`.

- `pytest-cov` will live in the development dependency group.
- Coverage collection will be scoped to `src/copilot_experiments`.
- Branch coverage will be enabled so reports catch missing decision paths, not just missing lines.
- GitHub Actions will run the test suite with coverage reporting.
- The pre-push hook will continue to run plain pytest so local pushes stay fast; developers can run
  coverage explicitly when they need the report.
- We will not set an initial hard coverage threshold. The first step is to establish a reliable
  baseline before deciding whether a gate is useful.

## Consequences

- Contributors can get coverage feedback with the same pytest workflow they already use.
- CI records coverage output without introducing Codecov, Coveralls, or another hosted dependency.
- `coverage.py` remains available underneath `pytest-cov`, so the project can later add XML, HTML,
  branch-specific, or diff-oriented reporting without changing tools.
- Without an initial threshold, coverage regressions are visible but not automatically blocked. A
  future ADR or follow-up change can introduce a threshold once the baseline is understood.
