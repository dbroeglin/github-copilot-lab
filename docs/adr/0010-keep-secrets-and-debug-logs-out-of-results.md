# 0010. Keep secrets and bulky debug logs out of stored results

- **Status:** Accepted
- **Date:** 2026-06-15
- **Deciders:** project owner, Copilot

## Context

A review of what a real `run` actually persists under `results/` surfaced two hygiene gaps:

1. **Copilot's own debug log was persisted.** We passed `--log-dir <trial>/logs`, so every trial
   left a multi-megabyte `logs/process-*.log` (one real run was 3.4 MB / ~39k lines). That file
   is Copilot's verbose internal log — *not* our data source. Per
   [ADR-0004](0004-session-log-is-primary-data-source.md), all metrics and analysis come from the
   session `events.jsonl`. The debug log was pure weight, and although Copilot already masks
   credentials in it (`"token": "******"`), it echoes auth-flow chatter ("OAuth required", etc.).
   It is a fragile place to *trust* for secret hygiene and a poor thing to keep around.
2. **The `Variant.env` escape hatch was stored verbatim.** BYOK secrets go through
   `ProviderConfig`, whose `redacted()` masks `api_key` / `bearer_token`
   (see [BYOK guide](../byok-and-local-models.md)). But `Variant.env` is a free-form
   `dict[str, str]` that a user could use to pass `GITHUB_TOKEN`, `OPENAI_API_KEY`, etc. — and
   `Variant.stored()` wrote it straight into `variant.json` (and the index `params_json`).

The user explicitly asked that we **not** persist data/DB files beyond what running an experiment
requires, and that we **not** capture GitHub / Copilot tokens when collecting logs.

## Decision

- **Don't persist Copilot's `--log-dir` debug log.** `_run_trial` now points `--log-dir` at an
  ephemeral `tempfile.mkdtemp()` and removes it in a `finally` (`force_rmtree`). Nothing lands
  under `results/<...>/trials/<NN>/logs/` anymore. Diagnostics that matter — the actual event
  stream, including any error Copilot prints — remain in the captured `stdout.jsonl`.
- **Redact secret-looking environment variables in stored artifacts.** `Variant.stored()` now
  masks the *value* of any `env` key whose name matches a secret hint
  (`key|token|secret|password|passwd|bearer|credential|authorization`, case-insensitive) with
  `***redacted***`. This is a safety net on top of the (preferred) `ProviderConfig` path; the
  full, unredacted `env` is still passed to the Copilot subprocess at runtime — it is only the
  *persisted* copy that is masked.

## Consequences

- `results/` shrinks dramatically per trial and no longer contains Copilot's internal debug log.
  The on-disk layout in [results-format](../results-format.md) is unchanged (it never listed
  `logs/`); a regression test asserts no `logs/` directory is written.
- A token accidentally placed in `Variant.env` cannot leak into `variant.json` or the SQLite
  index. Over-masking a benign-but-secret-named variable is acceptable (fail safe); the runtime
  value the subprocess sees is untouched.
- `events.jsonl`, `stdout.jsonl`, `analysis.json`, `metrics.json`, `meta.json`, `verify.json`,
  and `variant.json` were audited and contain no harness-injected credentials.
- **Trade-off:** Copilot's verbose debug log is gone even on failure. We accept this because
  `stdout.jsonl` already carries the failure output (it is how the `ENAMETOOLONG` bug in
  [ADR-0009](0009-absolute-workspace-path-for-copilot.md) was diagnosed). A future option is a
  `--keep-copilot-logs` flag for deep debugging.
