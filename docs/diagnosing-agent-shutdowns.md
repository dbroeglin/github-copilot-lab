# Diagnosing agent shutdowns and timeouts

When a Copilot CLI trajectory "stops" partway — at a fixed-looking number of turns, with a
failed grade, or in a way that looks truncated — the reflex is to blame a *limit* ("it hit the
turn cap") or the *network* ("the egress proxy hung again"). This page records what those
symptoms actually mean, how to tell them apart from the run artifacts, and how to remediate. It
is grounded in a real DeepSWE run (an OPA template-string bugfix task) that ended at 95 turns
with reward 0.0.

> **Observed, not documented.** Most specifics here come from run artifacts (`events.jsonl`, the
> Copilot CLI process log) and the CLI's own `copilot help limits` — not from public
> documentation. Treat internal env vars and log strings as build-specific and re-verify against
> your Copilot CLI version. The same caveat the event schema carries in
> [Collecting data from a Copilot CLI run](collecting-run-data.md#publicly-documented-vs-observed)
> applies here.

## There is no turn limit

A run that stops at *N* turns did not hit a turn cap — none exists at any layer:

- **This harness.** The `copilot-cli` Pier agent sets no turn cap and no per-run timeout by
  default (see [`copilot_cli.py`](../src/copilot_experiments/pier_agents/copilot_cli.py)).
- **The CLI.** `copilot help limits` shows the only session limit is `--max-ai-credits` — an
  opt-in *soft AIU cap* (minimum 30), not a turn count. `--max-autopilot-continues` (default 5)
  applies to autopilot mode only; it has no effect on the non-interactive `-p` path this harness
  uses.
- **The task.** A DeepSWE `task.toml` `[agent] timeout_sec` (for example `5400` = 90 minutes) is
  a wall-clock budget, not a turn count.

So `n_turns` is incidental — it is simply where the session happened to be when *something else*
ended it. To find that something else, read the tail of `events.jsonl` and the process log; do
not attribute the stop to a cap that does not exist.

## The `600s` timeout is a ceiling, not a hang

On exit the CLI process log may show:

```text
waitForPendingBackgroundTasks timed out after 600s — proceeding with exit.
Set COPILOT_TASK_WAIT_TIMEOUT_SECONDS to increase.
Completing 17 orphaned tool calls.
```

Two things are routinely misread here:

- **`600s` is the configured *maximum* the CLI will wait for background work at shutdown**
  (`COPILOT_TASK_WAIT_TIMEOUT_SECONDS`, observed default `600`) — **not** a measured ten-minute
  hang. The line means "a background task was still pending when we decided to exit, so we waited
  up to the ceiling and then gave up." It says nothing about *how long* anything was actually
  stuck.
- **"Completing N orphaned tool calls" is exit bookkeeping.** These are tool calls that were
  in-flight or queued in the model conversation and never received results; on force-exit the CLI
  reconciles them with synthetic results. The reported count can *exceed* the number of unmatched
  `tool.execution_start` events in `events.jsonl` (in the OPA run the log said 17, but the event
  stream had exactly **one** start without a matching complete).

In `events.jsonl` the shutdown surfaces as an `abort` followed by a routine `session.shutdown`:

```text
… → assistant.message → tool.execution_start → abort(reason:"user_initiated") → session.shutdown
```

`reason: "user_initiated"` is the internal cancel/interrupt path the exit uses — **not** a
literal human pressing Ctrl-C.

## Tell a real hang from ordinary activity

The decisive test is a **gap analysis**: sort events by timestamp and look at the elapsed time
between consecutive events. A genuine hang is a *single* multi-minute dead zone. Continuous
activity — many short gaps interspersed with turns and tool calls — means nothing hung; the run
simply used its time.

Start with the harness's own renderer and scan the per-turn `dur` column:

```bash
uv run copilot-experiments analyze --file path/to/events.jsonl
```

For the raw inter-event gaps (robust to fractional-second timestamps):

```bash
uv run python - <<'PY'
import json
from datetime import datetime

rows = [json.loads(line) for line in open("events.jsonl")]
rows.sort(key=lambda e: e["timestamp"])

def ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

prev = None
for e in rows:
    t = ts(e["timestamp"])
    if prev is not None:
        gap = (t - prev[0]).total_seconds()
        if gap > 20:  # only the interesting stalls
            print(f"{gap:6.0f}s  after {prev[1]} {prev[2] or ''}")
    prev = (t, e["type"], (e.get("data") or {}).get("toolName", ""))
PY
```

Supporting checks:

- **Match `tool.execution_start` ↔ `tool.execution_complete` on `toolCallId`.** Only starts with
  no matching complete are genuinely unfinished.
- **Background shells are normal.** A *sync* `bash` call that outruns its `initial_wait`
  auto-backgrounds and is then polled with `read_bash`. An orphaned `read_bash` at the very end is
  just a poll caught mid-flight — not a stuck command.
- **Check the process log for network errors *during* the run, not just at startup.** A fast
  startup `404` (for example to the remote Task API) that fails immediately is unrelated to a
  mid-run stall.

## Is it the proxy?

In a sandboxed run (`allow_internet = false`, egress proxy) a blackholed network call is a real
failure mode — but it has a signature. Confirm it; do not assume it.

| Signal | Proxy / network stall | Ordinary long run (the OPA case) |
| --- | --- | --- |
| Gap analysis | one long dead zone (minutes of silence) | many short gaps; largest ~239s on a `go test` |
| LLM completions | stall too (same egress path) | keep flowing (turns, compaction continue) |
| Process log mid-run | `ETIMEDOUT` / `fetch failed` / socket errors | none; only a fast startup `404` |
| Tool output | network-dependent tools error out | `go test` compiled and produced real results |

If completions keep succeeding through the same proxy *and* shell tools produce real output, the
proxy is **not** the culprit for that run.

## Worked example: the OPA `go test ./...` run

A DeepSWE OPA template-string bugfix task ended at 95 turns, reward 0.0 (f2p 0/5, p2p 4/4). What
actually happened:

- The trial **completed cleanly** — `exception_info: null`, ~22.6 minutes of a 90-minute budget
  used. The grader failed; the run did not crash.
- **No 600s dead zone.** The largest inter-event gap was ~239s, spent waiting on a background
  `go test`. The lone orphaned call was a `read_bash` polling a still-running `go test ./...`.
- **Root cause: repeated full-suite test runs.** The agent ran the entire OPA suite
  (`go test ./...`, ~6 minutes each) several times instead of targeting the two packages it
  edited (`v1/ast`, `v1/format`). It burned its time budget re-testing unrelated code, never
  converged, and the exit path fired while one more full-suite run was in flight.
- **Not a proxy issue.** Zero mid-run network errors; completions flowed through the same egress
  proxy throughout; `go test` produced genuine OPA output.

## Remediation

Ranked by leverage:

1. **Steer the agent to targeted tests.** The real fix: `go test ./v1/ast/... ./v1/format/...`
   instead of `./...`. Full-suite runs on a large repo are the dominant time sink. Encode this in
   the task instruction / system prompt.
2. **Shorten the exit wait so shutdown fails fast.** Set `COPILOT_TASK_WAIT_TIMEOUT_SECONDS` (for
   example `60`) in the agent's `env` so the CLI does not linger up to 600s on a background task
   at exit. This changes the *cost of the symptom*, not the root cause.
3. **Only if a run really is network-bound**, confirm it against the proxy signature above, then
   allowlist the specific host in the egress proxy (or set `allow_internet = true`) — but only if
   the remote feature is genuinely wanted.

### Where the knobs plug in

- **Agent `env` reaches the Copilot subprocess.**
  [`pier_backend.py`](../src/copilot_experiments/pier_backend.py) injects auth into `agent.env`
  via `setdefault`, and [`copilot_cli.py`](../src/copilot_experiments/pier_agents/copilot_cli.py)
  merges it into the process env in `run()`. `env` is a top-level agent field.
- **Arbitrary CLI flags flow through `extra_args`** — a `CopilotCli` constructor kwarg rendered by
  `_extra_args_string()` and appended to the `copilot -p …` command line. In a job config it goes
  under the agent's `kwargs`.
- **`build_deepswe_job_config` does not yet expose `env` or `extra_args`**
  ([`deepswe.py`](../src/copilot_experiments/deepswe.py)). Until it does, add them by hand to the
  generated job YAML:

```yaml
agents:
  - name: copilot-cli
    model_name: gpt-5-mini
    kwargs:
      reasoning_effort: medium
      # extra_args: "--some-flag"   # arbitrary copilot CLI flags, if needed
    env:
      COPILOT_TASK_WAIT_TIMEOUT_SECONDS: "60"
```

## Quick checklist

- [ ] Stopped at *N* turns? There is **no turn limit** — find what ended it; do not blame a cap.
- [ ] `waitForPendingBackgroundTasks … 600s`? That is the **ceiling**, not a measured hang.
- [ ] Run a **gap analysis** — one long dead zone = hang; many short gaps = ordinary long run.
- [ ] Completions and shell tools still producing output? **Not** the proxy.
- [ ] Time sink is a repeated broad command (for example `go test ./...`)? **Steer to targeted
      commands.**
