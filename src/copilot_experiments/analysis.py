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

from . import pricing
from .models import LlmCallSummary, PhaseStat, SessionAnalysis, ToolStat, TurnSummary
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


def analyze_events(
    events: list[dict[str, Any]], otel_records: list[dict[str, Any]] | None = None
) -> SessionAnalysis:
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

    if otel_records:
        _apply_otel_records(analysis, otel_records)

    return analysis


def _apply_otel_records(analysis: SessionAnalysis, records: list[dict[str, Any]]) -> None:
    calls = llm_calls_from_otel(records)
    if not calls:
        return

    analysis.llm_calls = calls
    turns_by_id = {turn.turn_id: turn for turn in analysis.turns if turn.turn_id is not None}
    for call in calls:
        if call.turn_id is None:
            continue
        turn = turns_by_id.get(str(call.turn_id))
        if turn is None:
            continue
        _add_turn_int(turn, "input_tokens", call.input_tokens)
        _add_turn_int(turn, "cache_read_input_tokens", call.cache_read_input_tokens)
        _add_turn_int(turn, "cache_creation_input_tokens", call.cache_creation_input_tokens)
        if turn.output_tokens is None:
            _add_turn_int(turn, "output_tokens", call.output_tokens)
        _add_turn_float(turn, "aiu", call.aiu)
        _add_turn_int(turn, "api_duration_ms", call.server_duration_ms)

    # If a native shutdown exists, it remains authoritative for aggregate economics. If not, OTel
    # still lets direct-file analyses recover useful totals from chat spans.
    if analysis.economics.total_tokens is not None:
        return

    input_tokens = _sum_int(call.input_tokens for call in calls)
    cache_read_tokens = _sum_int(call.cache_read_input_tokens for call in calls)
    cache_creation_tokens = _sum_int(call.cache_creation_input_tokens for call in calls)
    output_tokens = _sum_int(call.output_tokens for call in calls)
    api_duration_ms = _sum_int(call.server_duration_ms for call in calls)
    aiu = _sum_float(call.aiu for call in calls)

    if input_tokens is not None:
        analysis.input_tokens = input_tokens
        analysis.economics.input_tokens_total = input_tokens
    if cache_read_tokens is not None:
        analysis.economics.cache_read_tokens = cache_read_tokens
    if cache_creation_tokens is not None:
        analysis.economics.cache_write_tokens = cache_creation_tokens
    if output_tokens is not None:
        analysis.output_tokens = output_tokens
        analysis.economics.output_tokens = output_tokens
    if input_tokens is not None or output_tokens is not None:
        total = (input_tokens or 0) + (output_tokens or 0)
        analysis.total_tokens = total
        analysis.economics.total_tokens = total
    if aiu is not None:
        analysis.economics.aiu = round(aiu, 6)
    if api_duration_ms is not None:
        analysis.economics.api_duration_ms = api_duration_ms
    analysis.economics.n_requests = len(calls)


def llm_calls_from_otel(records: list[dict[str, Any]]) -> list[LlmCallSummary]:
    """Extract Copilot LLM-call summaries from OTel file-exporter records."""

    calls: list[LlmCallSummary] = []
    for record in records:
        if record.get("type") != "span":
            continue
        name = str(record.get("name") or "")
        attrs = _otel_attrs(record.get("attributes"))
        if attrs.get("gen_ai.operation.name") != "chat" and not name.startswith("chat "):
            continue

        start = _parse_otel_time(record.get("startTime") or record.get("startTimeUnixNano"))
        end = _parse_otel_time(record.get("endTime") or record.get("endTimeUnixNano"))
        duration = round((end - start).total_seconds(), 3) if start and end else None
        usage_info = _chat_usage_event(record.get("events"))
        nano_aiu = _otel_number(attrs.get("github.copilot.nano_aiu"))
        input_tokens = _otel_int(attrs.get("gen_ai.usage.input_tokens"))
        output_tokens = _otel_int(attrs.get("gen_ai.usage.output_tokens"))

        calls.append(
            LlmCallSummary(
                turn_id=_otel_string(attrs.get("github.copilot.turn_id")),
                started_at=_iso_z(start),
                ended_at=_iso_z(end),
                duration_s=duration,
                request_model=_string_or_none(attrs.get("gen_ai.request.model")),
                response_model=_string_or_none(attrs.get("gen_ai.response.model"))
                or _model_from_span_name(name),
                response_id=_otel_string(attrs.get("gen_ai.response.id")),
                finish_reasons=_strings(attrs.get("gen_ai.response.finish_reasons")),
                input_tokens=input_tokens,
                cache_read_input_tokens=_first_otel_int(
                    attrs,
                    "gen_ai.usage.cache_read.input_tokens",
                    "gen_ai.usage.cache_read_input_tokens",
                    "gen_ai.usage.cache_read_tokens",
                    "gen_ai.usage.cached_input_tokens",
                    "gen_ai.usage.cached_tokens",
                    "gen_ai.usage.prompt_tokens_details.cached_tokens",
                    "gen_ai.usage.input_token_details.cached_tokens",
                    "gen_ai.usage.input_token_details.cache_read_tokens",
                    "gen_ai.usage.input_tokens_details.cached_tokens",
                ),
                cache_creation_input_tokens=_first_otel_int(
                    attrs,
                    "gen_ai.usage.cache_creation.input_tokens",
                    "gen_ai.usage.cache_creation_input_tokens",
                ),
                output_tokens=output_tokens,
                total_tokens=(
                    (input_tokens or 0) + (output_tokens or 0)
                    if input_tokens is not None or output_tokens is not None
                    else None
                ),
                aiu=pricing.to_aiu(nano_aiu),
                server_duration_ms=_otel_int(attrs.get("github.copilot.server_duration")),
                current_tokens=_otel_int(usage_info.get("github.copilot.current_tokens")),
                token_limit=_otel_int(usage_info.get("github.copilot.token_limit")),
                interaction_id=_otel_string(attrs.get("github.copilot.interaction_id")),
                service_request_id=_otel_string(attrs.get("github.copilot.service_request_id")),
            )
        )
    return calls


_llm_calls_from_otel = llm_calls_from_otel


def _chat_usage_event(events: Any) -> dict[str, Any]:
    if not isinstance(events, list):
        return {}
    for event in events:
        if not isinstance(event, dict) or event.get("name") != "github.copilot.session.usage_info":
            continue
        return _otel_attrs(event.get("attributes"))
    return {}


def _first_otel_int(attrs: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = _otel_attr_value(attrs, key)
        if value is None:
            continue
        parsed = _otel_int(value)
        if parsed is not None:
            return parsed
    return None


def _otel_attr_value(attrs: dict[str, Any], key: str) -> Any:
    if key in attrs:
        return attrs[key]
    parts = key.split(".")
    for index in range(len(parts) - 1, 0, -1):
        prefix = ".".join(parts[:index])
        value = attrs.get(prefix)
        if not isinstance(value, dict):
            continue
        for part in parts[index:]:
            value = value.get(part) if isinstance(value, dict) else None
        return value
    return None


def _otel_attrs(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return {str(k): _otel_value(v) for k, v in raw.items()}
    if isinstance(raw, list):
        attrs: dict[str, Any] = {}
        for item in raw:
            if isinstance(item, dict) and item.get("key") is not None:
                attrs[str(item["key"])] = _otel_value(item.get("value"))
        return attrs
    return {}


def _otel_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if key in value:
            return value[key]
    if "arrayValue" in value:
        values = (value["arrayValue"] or {}).get("values") or []
        return [_otel_value(v) for v in values]
    if "kvlistValue" in value:
        entries = (value["kvlistValue"] or {}).get("values") or []
        return _otel_attrs(entries)
    return value


def _parse_otel_time(value: Any) -> _dt.datetime | None:
    value = _otel_value(value)
    if isinstance(value, str):
        try:
            return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                return _parse_otel_time(float(value))
            except ValueError:
                return None
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            seconds = int(value[0])
            nanos = int(value[1])
        except (TypeError, ValueError):
            return None
        return _dt.datetime.fromtimestamp(seconds, tz=_dt.UTC) + _dt.timedelta(
            microseconds=nanos / 1000
        )
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value)
        if seconds > 1_000_000_000_000_000:
            seconds /= 1_000_000_000
        elif seconds > 1_000_000_000_000:
            seconds /= 1000
        try:
            return _dt.datetime.fromtimestamp(seconds, tz=_dt.UTC)
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _iso_z(value: _dt.datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(_dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _otel_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _otel_int(value: Any) -> int | None:
    number = _otel_number(value)
    return int(number) if number is not None else None


def _strings(value: Any) -> list[str]:
    value = _otel_value(value)
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if isinstance(value, str) and value:
        return [value]
    return []


def _otel_string(value: Any) -> str | None:
    value = _otel_value(value)
    if value in (None, ""):
        return None
    if isinstance(value, (str, int, float)):
        return str(value)
    return None


def _model_from_span_name(name: str) -> str | None:
    prefix = "chat "
    return name[len(prefix) :] if name.startswith(prefix) and len(name) > len(prefix) else None


def _sum_int(values: Any) -> int | None:
    total = 0
    seen = False
    for value in values:
        if value is None:
            continue
        total += int(value)
        seen = True
    return total if seen else None


def _sum_float(values: Any) -> float | None:
    total = 0.0
    seen = False
    for value in values:
        if value is None:
            continue
        total += float(value)
        seen = True
    return total if seen else None


def _add_turn_int(turn: TurnSummary, field: str, value: int | None) -> None:
    if value is None:
        return
    current = getattr(turn, field)
    setattr(turn, field, value if current is None else current + value)


def _add_turn_float(turn: TurnSummary, field: str, value: float | None) -> None:
    if value is None:
        return
    current = getattr(turn, field)
    setattr(turn, field, value if current is None else round(current + value, 6))


def analyze_trajectory(trajectory: dict[str, Any]) -> SessionAnalysis:
    """Reconstruct a :class:`SessionAnalysis` from an ATIF ``trajectory.json``.

    Native Copilot ``events.jsonl`` remains the richer source of truth. This fallback covers Pier
    jobs where the Copilot CLI produced structured JSON/ATIF but did not emit native session events.
    """

    analysis = SessionAnalysis(
        session_id=_string_or_none(trajectory.get("session_id")),
        producer="ATIF trajectory",
    )
    agent = trajectory.get("agent") or {}
    if isinstance(agent, dict):
        analysis.copilot_version = _string_or_none(agent.get("version"))
        _add_model(analysis.models, agent.get("model_name"))

    steps = trajectory.get("steps") or []
    if not isinstance(steps, list):
        steps = []
    analysis.n_events = len(steps)

    timestamps: list[_dt.datetime] = []
    output_tokens = 0
    saw_output_tokens = False
    tool_stats: dict[str, ToolStat] = {}

    for step in steps:
        if not isinstance(step, dict):
            continue

        timestamp = _string_or_none(step.get("timestamp"))
        ts = _parse_ts(timestamp)
        if ts is not None:
            timestamps.append(ts)
        _add_model(analysis.models, step.get("model_name"))

        source = step.get("source")
        if source == "user":
            analysis.n_user_messages += 1
            continue
        if source != "agent":
            continue

        analysis.n_assistant_messages += 1
        tool_calls = _trajectory_tool_calls(step)
        tool_names = [name for name, _call_id in tool_calls]
        for name, call_id in tool_calls:
            analysis.n_tool_calls += 1
            stat = tool_stats.setdefault(name, ToolStat(name=name))
            stat.calls += 1
            if _trajectory_tool_failed(step, call_id):
                stat.failures += 1
                analysis.n_tool_failures += 1

        completion_tokens = _int_or_none((step.get("metrics") or {}).get("completion_tokens"))
        if completion_tokens is not None:
            output_tokens += completion_tokens
            saw_output_tokens = True

        turn = TurnSummary(
            turn_no=len(analysis.turns) + 1,
            started_at=timestamp,
            assistant_messages=1,
            text_preview=_preview(step.get("message")),
            tools=tool_names,
            output_tokens=completion_tokens,
        )
        analysis.turns.append(turn)

    analysis.n_turns = len(analysis.turns)
    analysis.tools = sorted(tool_stats.values(), key=lambda s: (-s.calls, s.name))
    analysis.phases = _compute_phases(analysis.turns)

    final_metrics = trajectory.get("final_metrics") or {}
    if isinstance(final_metrics, dict):
        prompt_tokens = _int_or_none(final_metrics.get("total_prompt_tokens"))
        completion_tokens = _int_or_none(final_metrics.get("total_completion_tokens"))
        cached_tokens = _int_or_none(final_metrics.get("total_cached_tokens"))
        if prompt_tokens is not None:
            analysis.input_tokens = prompt_tokens
            analysis.economics.input_tokens_total = prompt_tokens
            analysis.economics.input_tokens_noncached = prompt_tokens
        if completion_tokens is not None:
            analysis.output_tokens = completion_tokens
            analysis.economics.output_tokens = completion_tokens
        elif saw_output_tokens:
            analysis.output_tokens = output_tokens
            analysis.economics.output_tokens = output_tokens
        if cached_tokens is not None:
            analysis.economics.cache_read_tokens = cached_tokens
        if analysis.input_tokens is not None or analysis.output_tokens is not None:
            analysis.total_tokens = (analysis.input_tokens or 0) + (analysis.output_tokens or 0)
            analysis.economics.total_tokens = analysis.total_tokens
        extra = final_metrics.get("extra") or {}
        if isinstance(extra, dict):
            analysis.economics.aiu = _float_or_none(extra.get("aiu"))
            analysis.economics.reasoning_tokens = _int_or_none(extra.get("reasoning_tokens"))
            analysis.economics.peak_context_tokens = _int_or_none(extra.get("peak_context_tokens"))
            analysis.economics.n_compactions = _int_or_none(extra.get("summarization_count")) or 0
    elif saw_output_tokens:
        analysis.output_tokens = output_tokens

    if analysis.output_tokens is None and saw_output_tokens:
        analysis.output_tokens = output_tokens
    if analysis.economics.output_tokens is None and analysis.output_tokens is not None:
        analysis.economics.output_tokens = analysis.output_tokens
    if analysis.economics.total_tokens is None and (
        analysis.input_tokens is not None or analysis.output_tokens is not None
    ):
        analysis.total_tokens = (analysis.input_tokens or 0) + (analysis.output_tokens or 0)
        analysis.economics.total_tokens = analysis.total_tokens

    if timestamps:
        first, last = min(timestamps), max(timestamps)
        analysis.started_at = first.isoformat().replace("+00:00", "Z")
        analysis.finished_at = last.isoformat().replace("+00:00", "Z")
        analysis.duration_s = round((last - first).total_seconds(), 3)

    return analysis


def _trajectory_tool_calls(step: dict[str, Any]) -> list[tuple[str, str]]:
    calls = step.get("tool_calls") or []
    if not isinstance(calls, list):
        return []
    result: list[tuple[str, str]] = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        name = _string_or_none(call.get("function_name")) or "unknown"
        call_id = _string_or_none(call.get("tool_call_id")) or ""
        result.append((name, call_id))
    return result


def _trajectory_tool_failed(step: dict[str, Any], call_id: str) -> bool:
    observation = step.get("observation") or {}
    if not isinstance(observation, dict):
        return False
    results = observation.get("results") or []
    if not isinstance(results, list):
        return False
    for result in results:
        if not isinstance(result, dict):
            continue
        if call_id and result.get("source_call_id") not in (call_id, None):
            continue
        content = _string_or_none(result.get("content")) or ""
        lowered = content.lower()
        if (
            '"code": "failure"' in lowered
            or '"code":"failure"' in lowered
            or '"code": "denied"' in lowered
            or '"code":"denied"' in lowered
            or "permission denied" in lowered
        ):
            return True
    return False


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
