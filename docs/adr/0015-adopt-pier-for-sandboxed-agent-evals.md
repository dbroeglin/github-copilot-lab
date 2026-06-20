# 0015. Adopt Pier for sandboxed agent evaluations

- **Status:** Accepted
- **Date:** 2026-06-19
- **Deciders:** project owner, Copilot

## Context

The original harness directly provisioned workspaces, invoked `copilot`, ran a local verifier, and
wrote a custom `results/` tree. That worked for Copilot CLI experiments, but it duplicated the
sandbox/task/verifier/artifact substrate that DeepSWE, Harbor, and Pier already model well.

The next direction is broader: keep Copilot CLI session capture as the project's differentiated
value, but make it possible to evaluate other Pier agents and use Harbor/Pier task directories.

## Decision

Use upstream `datacurve-pier` as the primary execution backend.

- Harbor/Pier task directories are the primary authoring format.
- Pier `JobConfig` YAML files under `experiments/` replace Python `Experiment` objects for new
  work.
- Pier job directories under `jobs/` are the canonical filesystem source for new runs.
- A local Pier installed agent, `copilot-cli`, shells out to the real GitHub Copilot CLI inside
  the sandbox.
- Native Copilot `events.jsonl` remains the primary source for Copilot-specific metrics and
  analysis.
- ATIF `trajectory.json` is captured for cross-agent compatibility and fallback metrics.
- Python 3.12 is the project baseline because Pier requires it.

Do not vendor Pier in this repository. If local Pier patches are needed while experimenting, use a
temporary uv source override to an editable sibling checkout.

## Consequences

- The old host-side runner/workspace/invoker path becomes legacy compatibility.
- `--dry-run` for Pier validates job configs; offline unit tests use fixture job directories rather
  than real Docker/Copilot.
- Results tooling must read both new Pier `jobs/` and old `results/` until migration is complete.
- Large SWE-style benchmark protocols should be handled by DeepSWE rather than this package.
- Contributing the `copilot-cli` installed agent upstream to Pier is now straightforward because it
  follows Pier's `BaseInstalledAgent` interface.

## Supersedes and amends

- Amends ADR-0002: the filesystem is still source of truth, but `jobs/` is canonical for new runs.
- Preserves ADR-0003: SQLite remains derived.
- Preserves ADR-0004: native Copilot session logs remain primary for Copilot analysis.
- Supersedes ADR-0005 and ADR-0008 for Pier runs: the mock invoker/dry-run strategy is legacy.
- Supersedes ADR-0009 for Pier runs: Pier controls the sandbox cwd; the Copilot agent still passes
  explicit session/log paths.
- Supersedes ADR-0012: Pier's `agents x tasks x n_attempts` is the primary matrix.
- Superseded by ADR-0016 for large benchmark protocols: DeepSWE is the benchmark path, not in-tree
  benchmark support.
