# 0012. Auth preflight, harness-failure status, and richer trial diagnostics

- **Status:** Accepted
- **Date:** 2026-06-16
- **Deciders:** Project maintainers

## Context

Running an experiment in an environment without a usable GitHub token (observed first in WSL
with broken DNS) produced a misleading result: each trial provisioned a workspace, invoked
`copilot`, and got `Error: No authentication information found.` Copilot exited `1` with an
empty session log. The run still "succeeded" structurally — the summary table rendered a clean
`0%` success row — and only a soft warning hinted that something was wrong. Three problems:

1. A failure in *our tooling / the environment* (no auth, a bad working directory, a provisioning
   error) was indistinguishable from the *experiment* legitimately failing its verify step.
2. The captured process output lived in `stdout.jsonl`, a misleading name — when Copilot errors
   it prints plain text, not JSONL — and there was no human-readable transcript of a session.
3. Authentication was left entirely to the `copilot` subprocess, so a missing token was only
   discovered *after* every trial had wasted time provisioning and spinning up the CLI.

## Decision

We will be intentional about harness failures and authentication, and capture more to diagnose:

- **Preflight + inject the token.** Before a run starts, the CLI resolves a GitHub token from
  `COPILOT_GITHUB_TOKEN` / `GH_TOKEN` / `GITHUB_TOKEN`, falling back to `gh auth token`
  (`copilot_experiments.auth`). With no token the run aborts immediately with actionable guidance
  and exit code `1` — no trials are wasted. The resolved token is injected into every trial's
  environment (`Invocation.env_overrides`).
- **Never leak the token.** It is only ever placed in a child process's runtime environment —
  never written to an artifact, never logged (only its *source* is printed). The carrying
  variable, plus any BYOK provider secrets, are passed to `copilot --secret-env-vars` so Copilot
  strips them from shell/MCP environments and redacts their values from its own output (including
  the shared markdown).
- **Classify each trial's outcome.** `TrialResult.status` ∈ `ok` / `copilot_failed` /
  `harness_error`, orthogonal to `success` (the verify result). It rolls up to
  `ExperimentRun.status` ∈ `completed` / `partial` / `failed`. Other experiments keep running on a
  failure; the `run` command exits `2` when any run is `partial` or `failed`.
- **Capture more, named honestly.** `stdout.jsonl` becomes `stdout.txt` (raw stdout/stderr —
  plain text). A new `session.md` is Copilot's markdown transcript via `--share=<trial>/session.md`
  (written outside the workspace so it never pollutes the diff). `events.jsonl` remains the
  structured source. Each failed trial's `error` + `error_artifact` point at the file to inspect.

## Consequences

- A broken environment now fails loudly and early instead of masquerading as a `0%` run, and CI
  can branch on the distinct exit codes (`0` clean, `2` harness/infra trouble, `1` usage error).
- The token-handling surface is concentrated in `auth.py` and exercised offline (the `gh`
  fallback is monkeypatched); a regression test asserts the token never appears in any persisted
  artifact.
- `meta.json` and the `trials` index table gain `status` / `error` columns. The index is a derived
  cache, but `connect()` ALTERs the new columns onto any pre-existing `index.db` to avoid forcing
  a `reindex`.
- ADR-0009 and ADR-0010 reference the old `stdout.jsonl` name; they are left as historical record.
  This ADR supersedes that naming.
