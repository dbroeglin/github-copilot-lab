# 0009. Copilot is always invoked with an absolute workspace path

- **Status:** Superseded by [ADR-0015](0015-adopt-pier-for-sandboxed-agent-evals.md) for Pier runs
- **Date:** 2026-06-15
- **Deciders:** project owner, Copilot

> **Amendment (ADR-0015):** Pier owns sandbox working directories for new runs. The Copilot Pier
> agent still passes explicit session/log paths, but the old host-side `-C` invariant is legacy.

## Context

The first genuine (non-mock) `run` against `examples/tracer_bullet` looked like it succeeded —
the CLI printed a clean summary table — but Copilot had in fact done nothing: `success 0%`,
`0 turns`, `0 tool calls`, and a ~1.8s duration. The captured `stdout.jsonl` revealed why:

```
error: cannot change working directory to 'examples\tracer_bullet\results\...\workspace':
ENAMETOOLONG: name too long, chdir '...\workspace' -> '...\workspace\examples\tracer_bullet\results\...\workspace'
```

Two harness behaviours combined into this bug:

1. `CopilotInvoker` set the child process `cwd` to the trial workspace **and** passed the same
   path to Copilot's `-C` flag.
2. Because the experiment was launched with a **relative** `--root` (`examples/tracer_bullet`),
   that path was relative. Copilot resolves `-C` *after* its process cwd is already the
   workspace, so a relative `-C` was joined onto the workspace — doubling the path
   (`...\workspace\...\workspace`) and overflowing Windows' `MAX_PATH`. Copilot aborted before
   doing any work, wrote no session log, and exited non-zero.

The empty session log then parsed to zero turns, and the summary still rendered — so a hard
failure masqueraded as a clean run. This is exactly the "I get a summary but nothing happened"
symptom the user reported.

## Decision

- **Always pass an absolute path to Copilot.** `build_args` resolves both `-C` and `--log-dir`
  to absolute paths, and `CopilotInvoker` resolves the process `cwd` the same way. An absolute
  `-C` is idempotent with the process cwd (no doubling), regardless of how `--root` was spelled.
- **Resolve `root` once, at the source.** `run_experiment` does
  `root = Path(root or Path.cwd()).resolve()`, so every derived path (results tree, workspace,
  fixtures, recorded `meta.json` paths) is absolute. A relative `--root` can no longer leak into
  a child process.
- **Never let a failed invocation look clean.** After printing the summary, the CLI inspects each
  trial and prints a prominent warning when `exit_code != 0` or no session log was captured
  (`n_turns == 0`), pointing at the trial's `stdout.jsonl`.

## Consequences

- Real runs work from a relative or absolute `--root`; the tracer-bullet experiment now completes
  end-to-end (Copilot edits the workspace, the session log is captured from
  `~/.copilot/session-state/<session-id>/events.jsonl`, metrics parse, verification passes).
- A broken Copilot invocation is now obvious at a glance instead of hiding behind a zero-turn row.
- A regression test asserts `-C` (and `--log-dir`) are absolute, so the doubling cannot silently
  return.
- **Known limitation (not fully solved here):** Windows' default `MAX_PATH` (260) still constrains
  how deep the results tree can be. The trial workspace path
  (`results/<slug>/<run-id>/variants/<variant>/trials/<NN>/workspace/...`) is long; very deep
  experiment roots or long fixture paths could still exceed the limit. Mitigations to consider
  later: shorter on-disk layout, enabling long-path support, or honouring a configurable results
  root on a short drive. Capturing the diff already uses `git -c core.longpaths=true`.
