# 0020. Remove the legacy native harness

- **Status:** Accepted
- **Date:** 2026-06-28
- **Deciders:** Project maintainers

## Context

The project had two overlapping execution models:

- the original native Python harness, with `Experiment`, `Task`, `Variant`, `run_experiment()`,
  mock/dry-run execution, `results/<experiment>/<run>/`, and a derived SQLite index; and
- Pier jobs, with `JobConfig`, `agents:`, tasks/datasets, attempts, and `jobs/<job>/<run-id>/`.

Keeping both models made the CLI hard to explain. Users configured Pier `agents:` but then had to
look for "variants", use raw `--trial` selectors to find a particular agent result, and learn
whether `run --dry-run` meant a mock execution or a Pier config-load check.

## Decision

`copilot-experiments` is Pier-only. We remove the native `Experiment`/`Task`/`Variant` runner,
workspace/invoker abstractions, old `results/` layout, SQLite index, `reindex`, and `run --dry-run`.

The active vocabulary is:

- **Job config**: Pier YAML/JSON under `experiments/`.
- **Job**: stable `job_name`.
- **Run**: concrete execution at `jobs/<job-name>/<run-id>/`.
- **Agent**: one Pier `agents:` entry and the comparison axis.
- **Task**: one task or dataset-expanded task.
- **Trial**: one attempt of an `(agent, task)` cell.

The CLI remains flat but speaks this vocabulary: `validate`, `run`, `list`, `show`, `inspect`, and
`analyze`. `validate` is a preflight, not a fake run: it loads Pier job configs, checks referenced
paths, runs backend preflights, and checks Copilot auth without creating a job directory.

## Consequences

- Old native experiment definitions and old `results/` trees are no longer readable by active CLI
  commands.
- `jobs/<job-name>/<run-id>/` is the only persisted execution layout.
- Cross-run discovery scans `jobs/` directly instead of using `results/index.db`.
- Summaries aggregate by agent, task, and trial rather than adapting agents into variants.
- Existing ADRs about the SQLite index and dry-run semantics are superseded for current behavior.
