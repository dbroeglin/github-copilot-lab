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
        str(inv.log_dir),
        "-C",
        str(inv.workspace),
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
    """Invoke the real Copilot CLI."""

    def __init__(self, binary: str = "copilot") -> None:
        self.binary = binary

    def run(self, inv: Invocation) -> InvocationResult:
        inv.log_dir.mkdir(parents=True, exist_ok=True)
        inv.stdout_path.parent.mkdir(parents=True, exist_ok=True)
        args = [self.binary, *build_args(inv)]
        env = build_env(inv)
        start = time.monotonic()
        with inv.stdout_path.open("w", encoding="utf-8") as out:
            proc = subprocess.run(
                args,
                cwd=str(inv.workspace),
                env=env,
                stdout=out,
                stderr=subprocess.STDOUT,
                text=True,
            )
        duration = time.monotonic() - start
        return InvocationResult(exit_code=proc.returncode, duration_s=duration)


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

        for i, (tool, text, ok) in enumerate(script):
            call_id = f"mock-{i}"
            events += [
                {"type": "assistant.turn_start", "timestamp": at(),
                 "data": {"turnId": str(i)}},
                {"type": "assistant.message", "timestamp": at(),
                 "data": {"model": model, "content": text, "turnId": str(i),
                          "outputTokens": 40 + 10 * i,
                          "toolRequests": [{"toolCallId": call_id, "name": tool}]}},
                {"type": "tool.execution_start", "timestamp": at(),
                 "data": {"toolCallId": call_id, "toolName": tool, "model": model,
                          "turnId": str(i)}},
                {"type": "tool.execution_complete", "timestamp": at(),
                 "data": {"toolCallId": call_id, "turnId": str(i), "success": ok}},
                {"type": "assistant.turn_end", "timestamp": at(),
                 "data": {"turnId": str(i)}},
            ]

        # A closing turn with a final message and no tool call.
        final_turn = len(script)
        events += [
            {"type": "assistant.turn_start", "timestamp": at(),
             "data": {"turnId": str(final_turn)}},
            {"type": "assistant.message", "timestamp": at(),
             "data": {"model": model, "turnId": str(final_turn), "outputTokens": 25,
                      "content": f"(mock) Completed the task for variant '{inv.variant.name}'."}},
            {"type": "assistant.turn_end", "timestamp": at(),
             "data": {"turnId": str(final_turn)}},
        ]
        return events
