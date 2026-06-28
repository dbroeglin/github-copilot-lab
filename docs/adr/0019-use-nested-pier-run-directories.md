# 0019. Use nested Pier run directories

- **Status:** Accepted
- **Date:** 2026-06-27
- **Deciders:** Project maintainers

## Context

Pier names each job output directory from `job_name`. Re-running the same experiment with the same
`job_name` would naturally target the same directory, while the previous harness behavior created
the first run at `jobs/<job-name>/` and later reruns at timestamp-suffixed sibling directories such
as `jobs/<job-name>-20260620-153000/`.

That mixed stable identity and concrete execution identity in one string. It also made command-line
lookup unclear: users could pass `--last`, but it was not obvious how to discover a run id, how to
select an earlier run, or whether a suffixed directory was a new job or a rerun of the same job.

The filesystem remains the source of truth, and `results/index.db` remains a derived cache. Existing
flat Pier job directories must remain readable during migration.

## Decision

We will store new Pier executions under `jobs/<job-name>/<run-id>/`.

The configured `job_name` is the stable experiment identity. Each concrete execution gets a
timestamp run id, with numeric collision suffixes when needed. The harness runs Pier by setting
Pier's `jobs_dir` to `jobs/<job-name>` and Pier's concrete `job_name` to the run id, then writes a
`copilot-experiments-run.json` manifest into the job output so summaries, indexing, and lookup can
recover the stable job name and concrete run id.

The CLI will expose copyable selectors through `copilot-experiments list`:

- `job-name/run-id` selects one exact Pier run.
- `job-name` selects the latest run for that Pier job.
- `--last` selects the most recent stored run overall.

Legacy flat Pier jobs at `jobs/<job-name>/` remain discoverable and resumable.

## Consequences

The output tree now separates stable job identity from repeated measurements, so reruns are easier
to compare and explain. `show`, `inspect`, and `analyze` can address exact runs without adding a
parallel command family.

The harness owns a small manifest file in each new Pier run directory because Pier's native
`config.json` only knows the concrete run id once the job is launched. Discovery must avoid
mistaking legacy flat job trial directories for nested runs; nested child directories under a legacy
flat job are treated as runs only when they contain the harness manifest.

Older flat jobs remain supported, but new documentation and generated experiment repos should teach
the nested layout and `list`-driven selector workflow.
