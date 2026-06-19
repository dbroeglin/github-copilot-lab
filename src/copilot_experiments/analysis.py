"""Turn a Copilot session ``events.jsonl`` into a structured :class:`SessionAnalysis`.

This is the analytic layer over a captured session log. Where :func:`sessionlog.parse_metrics`
produces a few flat counters for aggregation, this module reconstructs *what happened*: the
session header (model, effort, repo/branch), a per-turn timeline, and a per-tool histogram with
failures correlated back to the tool that produced them.

The output is plain pydantic data (no rendering), so it can be written to ``analysis.json``,
rendered in the CLI with Rich (see :mod:`render`), or served by a future web explorer.

Grounded in the real Copilot CLI event schema::

    session.start            -> selectedModel, reasoningEffort, copilotVersion, context{...}
    user.message             -> content
    assistant.turn_start     -> turnId
    assistant.message        -> model, content, toolRequests[], outputTokens
    tool.execution_start     -> toolName, toolCallId, model, turnId
    tool.execution_complete  -> toolCallId, success   (no toolName -> correlate via toolCallId)
    assistant.turn_end       -> turnId
    session.warning / hook.start / hook.end
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from .models import PhaseStat, SessionAnalysis, ToolStat, TurnSummary
from .sessionlog import extract_economics

_PREVIEW_LEN = 120

# Five contiguous temporal phases, mirroring the phase-level analysis in
# Bai et al. ("How Do AI Agents Spend Your Money?", Finding #6).
PHASE_NAMES = ("early", "early_mid", "mid", "later_mid", "later")
_N_PHASES = len(PHASE_NAMES)


def _phase_bounds(n: int, k: int = _N_PHASES) -> list[tuple[int, int]]:
    """Split ``n`` turns into ``k`` contiguous, near-equal ``[from, to)`` ranges.

    Mirrors ``numpy.array_split`` semantics (the first ``n % k`` groups are one
    larger) without taking a numpy dependency. Returns ``[]`` when ``n < k``.
    """
    if n < k:
        return []
    base, extra = divmod(n, k)
    bounds: list[tuple[int, int]] = []
    start = 0
    for i in range(k):
        size = base + (1 if i < extra else 0)
        bounds.append((start, start + size))
        start += size
    return bounds


def _compute_phases(turns: list[TurnSummary]) -> list[PhaseStat]:
    """Aggregate per-turn output/tool/duration signals into five temporal phases.

    Returns ``[]`` for sessions with fewer than five turns, where fifths carry
    no signal. ``output_share`` is each phase's fraction of total output tokens.
    """
    bounds = _phase_bounds(len(turns))
    if not bounds:
        return []
    total_out = sum((t.output_tokens or 0) for t in turns)
    phases: list[PhaseStat] = []
    for name, (lo, hi) in zip(PHASE_NAMES, bounds, strict=True):
        group = turns[lo:hi]
        out = sum((t.output_tokens or 0) for t in group)
        durations = [t.duration_s for t in group if t.duration_s is not None]
        phases.append(
            PhaseStat(
                name=name,
                turn_from=group[0].turn_no,
                turn_to=group[-1].turn_no,
                n_turns=len(group),
                n_tool_calls=sum(len(t.tools) for t in group),
                output_tokens=out,
                duration_s=round(sum(durations), 3) if durations else None,
                output_share=(out / total_out) if total_out else None,
            )
        )
    return phases


def _parse_ts(value: Any) -> _dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _preview(text: Any, limit: int = _PREVIEW_LEN) -> str | None:
    if not isinstance(text, str):
        return None
    flat = " ".join(text.split())
    if not flat:
        return None
    return flat if len(flat) <= limit else flat[: limit - 1] + "\u2026"


def _add_model(models: list[str], model: Any) -> None:
    if isinstance(model, str) and model and model not in models:
        models.append(model)


def analyze_events(events: list[dict[str, Any]]) -> SessionAnalysis:
    """Reconstruct a :class:`SessionAnalysis` from a list of session events."""
    analysis = SessionAnalysis()
    models: list[str] = []
    tool_names: dict[str, str] = {}  # toolCallId -> toolName
    tool_stats: dict[str, ToolStat] = {}  # toolName -> stat
    turns: list[TurnSummary] = []
    current: TurnSummary | None = None
    timestamps: list[_dt.datetime] = []
    out_tokens = 0
    in_tokens = 0
    saw_tokens = False

    analysis.n_events = len(events)

    for ev in events:
        etype = ev.get("type", "")
        data = ev.get("data", {}) or {}
        analysis.event_type_counts[etype] = analysis.event_type_counts.get(etype, 0) + 1

        ts = _parse_ts(ev.get("timestamp"))
        if ts is not None:
            timestamps.append(ts)

        if etype == "session.start":
            analysis.session_id = data.get("sessionId") or analysis.session_id
            analysis.copilot_version = data.get("copilotVersion")
            analysis.producer = data.get("producer")
            analysis.reasoning_effort = data.get("reasoningEffort")
            _add_model(models, data.get("selectedModel"))
            ctx = data.get("context") or {}
            analysis.repository = ctx.get("repository")
            analysis.branch = ctx.get("branch")
            analysis.cwd = ctx.get("cwd")
            analysis.started_at = data.get("startTime") or ev.get("timestamp")

        elif etype == "session.model_change":
            _add_model(models, data.get("newModel"))

        elif etype == "user.message":
            analysis.n_user_messages += 1

        elif etype == "assistant.turn_start":
            current = TurnSummary(
                turn_no=len(turns) + 1,
                turn_id=str(data.get("turnId")) if data.get("turnId") is not None else None,
                started_at=ev.get("timestamp"),
            )
            turns.append(current)
            analysis.n_turns += 1

        elif etype == "assistant.message":
            analysis.n_assistant_messages += 1
            _add_model(models, data.get("model"))
            out = data.get("outputTokens")
            inp = data.get("inputTokens")
            if isinstance(out, int):
                out_tokens += out
                saw_tokens = True
            if isinstance(inp, int):
                in_tokens += inp
                saw_tokens = True
            if current is not None:
                current.assistant_messages += 1
                if current.text_preview is None:
                    current.text_preview = _preview(data.get("content"))
                if isinstance(out, int):
                    current.output_tokens = (current.output_tokens or 0) + out

        elif etype == "tool.execution_start":
            name = data.get("toolName") or "unknown"
            call_id = data.get("toolCallId")
            if isinstance(call_id, str):
                tool_names[call_id] = name
            _add_model(models, data.get("model"))
            if current is not None:
                current.tools.append(name)

        elif etype == "tool.execution_complete":
            analysis.n_tool_calls += 1
            call_id = data.get("toolCallId")
            name = tool_names.get(call_id, "unknown") if isinstance(call_id, str) else "unknown"
            stat = tool_stats.setdefault(name, ToolStat(name=name))
            stat.calls += 1
            if data.get("success") is False:
                stat.failures += 1
                analysis.n_tool_failures += 1
            tele = (data.get("toolTelemetry") or {}).get("metrics") or {}
            duration = tele.get("durationMs")
            if isinstance(duration, (int, float)):
                stat.total_duration_ms += int(duration)
            chars = (
                tele.get("resultForLlmLength")
                or tele.get("resultLength")
                or tele.get("result_length")
            )
            if isinstance(chars, (int, float)):
                stat.total_result_chars += int(chars)

        elif etype == "assistant.turn_end":
            if current is not None:
                current.ended_at = ev.get("timestamp")
                start = _parse_ts(current.started_at)
                end = _parse_ts(current.ended_at)
                if start is not None and end is not None:
                    current.duration_s = round((end - start).total_seconds(), 3)
                current = None

        elif etype == "session.warning":
            analysis.n_warnings += 1
            msg = data.get("message")
            if isinstance(msg, str):
                analysis.warnings.append(msg)

        elif etype == "hook.start":
            analysis.n_hooks += 1

    analysis.models = models
    analysis.turns = turns
    analysis.phases = _compute_phases(turns)
    analysis.tools = sorted(tool_stats.values(), key=lambda s: (-s.calls, s.name))

    analysis.economics = extract_economics(events)
    econ = analysis.economics
    if econ.total_tokens is not None:
        # session.shutdown is authoritative when present.
        analysis.input_tokens = econ.input_tokens_total
        analysis.output_tokens = econ.output_tokens
        analysis.total_tokens = econ.total_tokens
    elif saw_tokens:
        analysis.output_tokens = out_tokens or None
        analysis.input_tokens = in_tokens or None
        analysis.total_tokens = (in_tokens + out_tokens) or None

    if timestamps:
        first, last = min(timestamps), max(timestamps)
        if analysis.started_at is None:
            analysis.started_at = first.isoformat().replace("+00:00", "Z")
        analysis.finished_at = last.isoformat().replace("+00:00", "Z")
        analysis.duration_s = round((last - first).total_seconds(), 3)

    return analysis
