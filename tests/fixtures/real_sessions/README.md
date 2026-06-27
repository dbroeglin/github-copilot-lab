# Real-session fixtures

Captured, **real** Copilot CLI session logs used to regression-test the session parsing,
economics, and analysis code against ground truth (not just hand-written synthetic events).

Each directory holds the two raw artifacts the Copilot CLI emits for a single trial:

- `events.jsonl` — the session event stream (`~/.copilot/session-state/<id>/events.jsonl`).
- `copilot-otel.jsonl` — the OTel span export (`--otel-file`), used to enrich the analysis.

| Directory              | Model                     | Task                         |
| ---------------------- | ------------------------- | ---------------------------- |
| `fix_bug_gpt55`        | `gpt-5.5`                 | Fix `multiply` in calculator |
| `fix_bug_claude_opus`  | `claude-opus-4.7`         | Fix `multiply` in calculator |
| `fix_bug_mai_flash`    | `mai-code-1-flash-picker` | Fix `multiply` in calculator |
| `fix_bug_gemini_pro`   | `gemini-3.1-pro-preview`  | Fix `multiply` in calculator |

## Provenance

These sessions were produced by running the *same* `example-fix-bug` task (patch a one-line
bug in `calculator.py`) through the real GitHub Copilot CLI (v1.0.65+) across several models.
They were captured in a sibling experiment harness and copied here verbatim — no values were
edited. `fix_bug_mai_flash` and `fix_bug_gemini_pro` additionally exercise model identifiers
beyond the Claude/GPT families (`mai-code-1-flash-picker`, `gemini-3.1-pro-preview`).

## Why these are trustworthy as "golden" values

The expected numbers asserted in `tests/test_real_sessions.py` were cross-checked two ways:

1. Against the raw `session.shutdown` payload (the CLI's own authoritative totals).
2. Against an **independent** source in the same log: summing the per-request AIU from the OTel
   `chat <model>` spans reproduces the shutdown's `totalNanoAiu` exactly. Two independent
   accountings agreeing is strong evidence the parser is correct.

These files contain no secrets (BYOK keys are never written to the event log); only prompts,
tool calls, token counts, and the harness's own file paths (e.g. `/app/calculator.py`).
