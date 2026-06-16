"""Build and execute the ``copilot`` command for a single trial.

Two implementations are provided:

* :class:`CopilotInvoker` shells out to the real ``copilot`` CLI.
* :class:`MockInvoker` simulates a run by writing synthetic ``events.jsonl`` and
  stdout, so the library, the runner, and experiment repos can be exercised
  end-to-end without consuming Copilot credits or network access.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from . import pricing
from ._util import iso, utcnow
from .models import Variant
from .sessionlog import events_path


@dataclass
class Invocation:
    prompt: str
    workspace: Path
    session_id: str
    variant: Variant
    log_dir: Path
    stdout_path: Path
    session_state_root: Path
    env_overrides: dict[str, str] = field(default_factory=dict)
    # Absolute path where Copilot should write its markdown session transcript
    # (``--share``). Kept *outside* the workspace so it never pollutes the diff.
    share_path: Path | None = None
    # Environment variable names Copilot must redact from its output and strip from
    # sub-shells (``--secret-env-vars``): the injected GitHub token and BYOK secrets.
    secret_env_names: list[str] = field(default_factory=list)


@dataclass
class InvocationResult:
    exit_code: int
    duration_s: float


class Invoker(Protocol):
    def run(self, inv: Invocation) -> InvocationResult: ...


def build_args(inv: Invocation) -> list[str]:
    """Translate a variant + invocation into ``copilot`` CLI arguments."""
    v = inv.variant
    args: list[str] = [
        "-p",
        inv.prompt,
        "--output-format",
        "json",
        "--session-id",
        inv.session_id,
        "--log-dir",
        str(Path(inv.log_dir).resolve()),
        "-C",
        # Always an absolute path: Copilot chdirs into ``-C`` *after* the process
        # cwd is already the workspace, so a relative value would be resolved
        # against the workspace and doubled (ENAMETOOLONG on Windows).
        str(Path(inv.workspace).resolve()),
    ]
    if v.allow_all_tools:
        args.append("--allow-all-tools")
    if v.model:
        args += ["--model", v.model]
    if v.reasoning_effort:
        args += ["--effort", v.reasoning_effort]
    if v.agent:
        args += ["--agent", v.agent]
    if v.mode:
        args += ["--mode", v.mode]
    for tool in v.allow_tools:
        args += ["--allow-tool", tool]
    for tool in v.deny_tools:
        args += ["--deny-tool", tool]
    # Redact injected token + BYOK secrets from Copilot's output (stdout, the shared
    # markdown transcript) and strip them from any shell/MCP sub-environments. Passed
    # as a single ``=``-joined token so the variadic option can't swallow later flags.
    if inv.secret_env_names:
        args.append(f"--secret-env-vars={','.join(inv.secret_env_names)}")
    # Write a human-readable markdown transcript of the session after completion. An
    # absolute path is required (and keeps it out of the workspace; ``--share`` would
    # otherwise default to the cwd, which is the diffed workspace).
    if inv.share_path is not None:
        args.append(f"--share={Path(inv.share_path).resolve()}")
    args += v.extra_args
    return args


def build_env(inv: Invocation) -> dict[str, str]:
    env = dict(os.environ)
    if inv.variant.provider is not None:
        env.update(inv.variant.provider.to_env())
    env.update(inv.variant.env)
    env.update(inv.env_overrides)
    return env


class CopilotInvoker:
    """Invoke the real Copilot CLI.

    When ``stream`` is provided, Copilot's combined stdout/stderr is *teed*: every
    line is both written to the capture file and forwarded to the callback, so the
    CLI's ``--verbose`` mode can follow the run live. When it is ``None`` the output
    is redirected straight to the file (the default, lowest-overhead path).
    """

    def __init__(
        self, binary: str = "copilot", *, stream: Callable[[str], None] | None = None
    ) -> None:
        self.binary = binary
        self.stream = stream

    def run(self, inv: Invocation) -> InvocationResult:
        inv.log_dir.mkdir(parents=True, exist_ok=True)
        inv.stdout_path.parent.mkdir(parents=True, exist_ok=True)
        args = [self.binary, *build_args(inv)]
        env = build_env(inv)
        # Always an absolute cwd for the same reason ``-C`` is absolute (see build_args).
        cwd = str(Path(inv.workspace).resolve())
        start = time.monotonic()
        if self.stream is None:
            exit_code = self._run_captured(args, cwd, env, inv.stdout_path)
        else:
            exit_code = self._run_streaming(args, cwd, env, inv.stdout_path)
        duration = time.monotonic() - start
        return InvocationResult(exit_code=exit_code, duration_s=duration)

    def _run_captured(
        self, args: list[str], cwd: str, env: dict[str, str], stdout_path: Path
    ) -> int:
        with stdout_path.open("w", encoding="utf-8") as out:
            proc = subprocess.run(
                args, cwd=cwd, env=env, stdout=out, stderr=subprocess.STDOUT, text=True
            )
        return proc.returncode

    def _run_streaming(
        self, args: list[str], cwd: str, env: dict[str, str], stdout_path: Path
    ) -> int:
        assert self.stream is not None
        with stdout_path.open("w", encoding="utf-8") as out:
            proc = subprocess.Popen(
                args,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                out.write(line)
                out.flush()
                self.stream(line.rstrip("\n"))
            return proc.wait()


class MockInvoker:
    """Simulate a Copilot run for testing and dry-runs.

    Writes a small synthetic ``events.jsonl`` (so :mod:`sessionlog` parsing works)
    and a matching stdout file. An optional ``solver`` callback may mutate the
    workspace to emulate Copilot completing the task (useful in tests).
    """

    def __init__(
        self,
        *,
        exit_code: int = 0,
        solver: Callable[[Path], None] | None = None,
        leave_note: bool = True,
        turns: int = 4,
    ) -> None:
        self.exit_code = exit_code
        self.solver = solver
        self.leave_note = leave_note
        self.turns = max(1, turns)

    def run(self, inv: Invocation) -> InvocationResult:
        model = inv.variant.model or "mock-model"
        start = time.monotonic()

        if self.solver is not None:
            self.solver(inv.workspace)
        elif self.leave_note:
            (inv.workspace / "MOCK_RUN.md").write_text(
                f"Mock Copilot run for variant '{inv.variant.name}'.\n", encoding="utf-8"
            )

        events = self._synthetic_events(inv, model)
        dest = events_path(inv.session_id, inv.session_state_root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("w", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")

        inv.stdout_path.parent.mkdir(parents=True, exist_ok=True)
        with inv.stdout_path.open("w", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")

        duration = time.monotonic() - start
        return InvocationResult(exit_code=self.exit_code, duration_s=duration)

    def _synthetic_events(self, inv: Invocation, model: str) -> list[dict]:
        """Build a small but realistic, multi-turn ``events.jsonl`` (real schema).

        Emits ``session.start`` / ``user.message`` and several assistant turns, each
        invoking a tool, so that downstream metrics *and* the richer session analysis
        have something meaningful to work with offline.
        """
        t0 = utcnow()
        clock = {"n": 0}

        def at() -> str:
            clock["n"] += 1
            return iso(t0 + _dt.timedelta(seconds=clock["n"] * 0.25))

        session_id = inv.session_id
        # A deterministic, varied tool script: one deliberate failure + recovery.
        script = [
            ("view", "Exploring the workspace to understand the task.", True),
            ("edit", "Applying the change to fix the issue.", True),
            ("powershell", "Running the verification command.", False),
            ("powershell", "Re-running verification after the fix.", True),
        ]
        script = script[: self.turns]

        events: list[dict] = [
            {
                "type": "session.start",
                "timestamp": at(),
                "data": {
                    "sessionId": session_id,
                    "producer": "mock",
                    "copilotVersion": "mock-0",
                    "selectedModel": model,
                    "reasoningEffort": inv.variant.reasoning_effort,
                    "context": {
                        "cwd": str(inv.workspace),
                        "branch": "mock",
                        "repository": "mock/experiment",
                    },
                    "startTime": iso(t0),
                },
            },
            {
                "type": "user.message",
                "timestamp": at(),
                "data": {"content": inv.prompt},
            },
        ]

        out_total = 0
        lines_added = 0
        lines_removed = 0
        for i, (tool, text, ok) in enumerate(script):
            call_id = f"mock-{i}"
            out_tok = 40 + 10 * i
            out_total += out_tok
            tele_metrics: dict = {
                "durationMs": 50 + 25 * i,
                "resultForLlmLength": 200 + 50 * i,
                "resultLength": 260 + 50 * i,
            }
            if tool == "edit":
                tele_metrics["linesAdded"] = 5
                tele_metrics["linesRemoved"] = 2
                lines_added += 5
                lines_removed += 2
            if tool == "powershell":
                tele_metrics["exit_code"] = 0 if ok else 1
            events += [
                {"type": "assistant.turn_start", "timestamp": at(),
                 "data": {"turnId": str(i)}},
                {"type": "assistant.message", "timestamp": at(),
                 "data": {"model": model, "content": text, "turnId": str(i),
                          "outputTokens": out_tok,
                          "toolRequests": [{"toolCallId": call_id, "name": tool}]}},
                {"type": "tool.execution_start", "timestamp": at(),
                 "data": {"toolCallId": call_id, "toolName": tool, "model": model,
                          "turnId": str(i)}},
                {"type": "tool.execution_complete", "timestamp": at(),
                 "data": {"toolCallId": call_id, "turnId": str(i), "success": ok,
                          "toolTelemetry": {"metrics": tele_metrics}}},
                {"type": "assistant.turn_end", "timestamp": at(),
                 "data": {"turnId": str(i)}},
            ]

        # A closing turn with a final message and no tool call.
        final_turn = len(script)
        out_total += 25
        events += [
            {"type": "assistant.turn_start", "timestamp": at(),
             "data": {"turnId": str(final_turn)}},
            {"type": "assistant.message", "timestamp": at(),
             "data": {"model": model, "turnId": str(final_turn), "outputTokens": 25,
                      "content": f"(mock) Completed the task for variant '{inv.variant.name}'."}},
            {"type": "assistant.turn_end", "timestamp": at(),
             "data": {"turnId": str(final_turn)}},
        ]

        events += self._economics_events(model, at, out_total, lines_added, lines_removed)
        return events

    @staticmethod
    def _economics_events(
        model: str,
        at: Callable[[], str],
        out_total: int,
        lines_added: int,
        lines_removed: int,
    ) -> list[dict]:
        """A self-consistent ``session.compaction_complete`` + ``session.shutdown`` pair.

        Token counts are priced with :mod:`pricing`'s documented rates so the synthetic
        ``totalNanoAiu`` reconciles exactly with the per-type decomposition -- exercising the full
        economics path (including ``rates_from_compaction``) entirely offline.
        """
        rates = pricing.default_rates()
        counts = {
            "input": 1500,
            "cache_read": 12_000,
            "cache_write": 2_000,
            "output": out_total,
        }
        reasoning_tokens = 120
        total_nano = int(sum(counts[t] * rates[t] for t in pricing.TOKEN_TYPES))
        input_billed = counts["input"] + counts["cache_read"] + counts["cache_write"]
        n_requests = 4
        return [
            {
                "type": "session.compaction_complete",
                "timestamp": at(),
                "data": {
                    "compactionTokensUsed": {
                        "copilotUsage": {
                            "totalNanoAiu": 5_000_000,
                            "tokenDetails": [
                                {
                                    "tokenType": t,
                                    "tokenCount": counts.get(t, 0),
                                    "batchSize": 1_000_000,
                                    "costPerBatch": pricing.DEFAULT_COST_PER_BATCH[t],
                                }
                                for t in pricing.TOKEN_TYPES
                            ],
                        }
                    },
                    "systemTokens": 9000,
                    "conversationTokens": 4000,
                    "toolDefinitionsTokens": 3000,
                },
            },
            {
                "type": "session.shutdown",
                "timestamp": at(),
                "data": {
                    "tokenDetails": {
                        "input": {"tokenCount": counts["input"]},
                        "cache_read": {"tokenCount": counts["cache_read"]},
                        "cache_write": {"tokenCount": counts["cache_write"]},
                        "output": {"tokenCount": counts["output"]},
                    },
                    "totalNanoAiu": total_nano,
                    "totalApiDurationMs": 1234 * n_requests,
                    "modelMetrics": {
                        model: {
                            "requests": {"count": n_requests},
                            "usage": {
                                "inputTokens": input_billed,
                                "outputTokens": counts["output"],
                                "cacheReadTokens": counts["cache_read"],
                                "cacheWriteTokens": counts["cache_write"],
                                "reasoningTokens": reasoning_tokens,
                            },
                            "totalNanoAiu": total_nano,
                        }
                    },
                    "systemTokens": 9000,
                    "conversationTokens": 4000,
                    "toolDefinitionsTokens": 3000,
                    "currentTokens": 16000,
                    "codeChanges": {
                        "filesModified": ["mock_file.py"],
                        "linesAdded": lines_added,
                        "linesRemoved": lines_removed,
                    },
                },
            },
        ]
