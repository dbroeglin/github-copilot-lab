"""Locate and parse Copilot CLI session logs (``events.jsonl``)."""

from __future__ import annotations

import datetime as _dt
import json
import shutil
from pathlib import Path
from typing import Any

from rich.console import Console

from . import pricing
from .models import Metrics, ModelMetric, TokenEconomics

err = Console(stderr=True)


def session_state_root(base: Path | None = None) -> Path:
    """Directory where the Copilot CLI stores per-session state."""
    if base is not None:
        return Path(base)
    return Path.home() / ".copilot" / "session-state"


def events_path(session_id: str, base: Path | None = None) -> Path:
    return session_state_root(base) / session_id / "events.jsonl"


def load_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    skipped_lines = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            skipped_lines += 1
            continue

    if skipped_lines > 0:
        err.print(
            f"[yellow]Warning: Skipped {skipped_lines} malformed JSON line(s) "
            f"in {path.name}[/yellow]"
        )

    return events


def copy_events(session_id: str, dest: Path, base: Path | None = None) -> bool:
    """Copy a session's ``events.jsonl`` to ``dest``. Returns True if it existed."""
    src = events_path(session_id, base)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        return False
    shutil.copyfile(src, dest)
    return True


def _parse_ts(value: str) -> _dt.datetime | None:
    try:
        return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _dig(data: Any, *keys: str) -> Any:
    cur = data
    for key in keys:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return None
    return cur


def _int(data: Any, *keys: str) -> int | None:
    value = _dig(data, *keys)
    return int(value) if isinstance(value, (int, float)) else None


def _token_count(shutdown: dict, ttype: str) -> int:
    return _int(shutdown, "tokenDetails", ttype, "tokenCount") or 0


def extract_economics(events: list[dict[str, Any]]) -> TokenEconomics:
    """Derive session-level token accounting and AIU cost from the event stream.

    Authoritative totals come from ``session.shutdown`` (summed across multiple shutdowns when a
    session was resumed; context composition and code changes are taken from the last one).
    ``session.compaction_*`` and ``session.truncation`` events contribute the context-growth peak,
    compaction cost, and live per-token AIU rates. Returns an all-``None`` economics object when
    the log carries no shutdown (e.g. an aborted session).
    """
    econ = TokenEconomics()
    shutdowns: list[dict] = []
    rates: dict[str, float] | None = None
    peak = 0
    compaction_nano = 0.0
    tokens_removed = 0

    for ev in events:
        etype = ev.get("type", "")
        data = ev.get("data", {}) or {}
        if etype == "session.shutdown":
            shutdowns.append(data)
        elif etype == "session.compaction_start":
            total = sum(
                v
                for v in (
                    _int(data, "systemTokens"),
                    _int(data, "conversationTokens"),
                    _int(data, "toolDefinitionsTokens"),
                )
                if v
            )
            peak = max(peak, total)
        elif etype == "session.compaction_complete":
            econ.n_compactions += 1
            if rates is None:
                rates = pricing.rates_from_compaction(data)
            peak = max(peak, _int(data, "preCompactionTokens") or 0)
            nano = _dig(data, "compactionTokensUsed", "copilotUsage", "totalNanoAiu")
            if isinstance(nano, (int, float)):
                compaction_nano += float(nano)
        elif etype == "session.truncation":
            econ.n_truncations += 1
            peak = max(peak, _int(data, "preTruncationTokensInMessages") or 0)
            tokens_removed += _int(data, "tokensRemovedDuringTruncation") or 0

    if shutdowns:
        last = shutdowns[-1]
        noncached = sum(_token_count(s, "input") for s in shutdowns)
        cache_read = sum(_token_count(s, "cache_read") for s in shutdowns)
        cache_write = sum(_token_count(s, "cache_write") for s in shutdowns)
        output = sum(_token_count(s, "output") for s in shutdowns)
        nano = sum(_int(s, "totalNanoAiu") or 0 for s in shutdowns)
        api_ms = sum(_int(s, "totalApiDurationMs") or 0 for s in shutdowns)

        per_model: dict[str, ModelMetric] = {}
        reasoning = 0
        requests = 0
        for s in shutdowns:
            mm = s.get("modelMetrics")
            if not isinstance(mm, dict):
                continue
            for name, m in mm.items():
                usage = m.get("usage") or {}
                count = _int(m, "requests", "count") or 0
                reasoning += int(usage.get("reasoningTokens") or 0)
                requests += count
                agg = per_model.setdefault(name, ModelMetric(model=name))
                agg.requests += count
                agg.input_tokens += int(usage.get("inputTokens") or 0)
                agg.output_tokens += int(usage.get("outputTokens") or 0)
                agg.cache_read_tokens += int(usage.get("cacheReadTokens") or 0)
                agg.cache_write_tokens += int(usage.get("cacheWriteTokens") or 0)
                agg.reasoning_tokens += int(usage.get("reasoningTokens") or 0)
                mnano = m.get("totalNanoAiu")
                if isinstance(mnano, (int, float)):
                    agg.aiu = round((agg.aiu or 0.0) + mnano / pricing.NANO_PER_AIU, 6)

        econ.input_tokens_noncached = noncached
        econ.cache_read_tokens = cache_read
        econ.cache_write_tokens = cache_write
        econ.output_tokens = output
        econ.reasoning_tokens = reasoning or None
        econ.input_tokens_total = noncached + cache_read + cache_write
        econ.total_tokens = econ.input_tokens_total + output
        econ.aiu = pricing.to_aiu(nano) if nano else None
        econ.n_requests = requests or None
        econ.api_duration_ms = api_ms or None
        econ.aiu_by_type = pricing.aiu_by_type(
            {
                "input": noncached,
                "cache_read": cache_read,
                "cache_write": cache_write,
                "output": output,
            },
            rates,
            normalize_to_nano=nano or None,
        )
        econ.system_tokens = _int(last, "systemTokens")
        econ.conversation_tokens = _int(last, "conversationTokens")
        econ.tool_definitions_tokens = _int(last, "toolDefinitionsTokens")
        econ.context_tokens = _int(last, "currentTokens")
        changes = last.get("codeChanges")
        if isinstance(changes, dict):
            files = changes.get("filesModified")
            econ.files_modified = (
                len(files) if isinstance(files, list) else _int(changes, "filesModified")
            )
            econ.lines_added = _int(changes, "linesAdded")
            econ.lines_removed = _int(changes, "linesRemoved")
        econ.model_metrics = list(per_model.values())

    peak = max(peak, econ.context_tokens or 0)
    econ.peak_context_tokens = peak or None
    econ.compaction_aiu = pricing.to_aiu(compaction_nano) if compaction_nano else None
    econ.tokens_removed_truncation = tokens_removed or None
    return econ


def parse_metrics(events: list[dict[str, Any]]) -> Metrics:
    """Derive trial metrics from a list of session events."""
    metrics = Metrics()
    models: list[str] = []
    timestamps: list[_dt.datetime] = []

    for ev in events:
        etype = ev.get("type", "")
        data = ev.get("data", {}) or {}

        ts = _parse_ts(ev.get("timestamp", ""))
        if ts is not None:
            timestamps.append(ts)

        if etype == "assistant.turn_start":
            metrics.n_turns += 1
        elif etype == "assistant.message":
            metrics.n_assistant_messages += 1
            model = data.get("model")
            if model:
                models.append(model)
            out = data.get("outputTokens")
            inp = data.get("inputTokens")
            if isinstance(out, int):
                metrics.output_tokens = (metrics.output_tokens or 0) + out
            if isinstance(inp, int):
                metrics.input_tokens = (metrics.input_tokens or 0) + inp
        elif etype == "tool.execution_complete":
            metrics.n_tool_calls += 1
            if data.get("success") is False:
                metrics.n_tool_failures += 1
            model = data.get("model")
            if model:
                models.append(model)
        elif etype == "tool.execution_start":
            model = data.get("model")
            if model:
                models.append(model)
        elif etype == "session.start":
            model = data.get("selectedModel")
            if model:
                models.append(model)
        elif etype == "session.model_change":
            model = data.get("newModel")
            if model:
                models.append(model)
        elif etype == "session.warning":
            metrics.n_warnings += 1

        # Token usage may appear on assistant messages / turn ends depending on
        # the Copilot version; probe a few common shapes defensively.
        for usage in (
            _dig(data, "usage"),
            _dig(data, "tokens"),
            _dig(data, "telemetry", "usage"),
        ):
            if isinstance(usage, dict):
                inp = (
                    usage.get("input_tokens")
                    or usage.get("inputTokens")
                    or usage.get("prompt_tokens")
                )
                out = (
                    usage.get("output_tokens")
                    or usage.get("outputTokens")
                    or usage.get("completion_tokens")
                )
                if inp is not None:
                    metrics.input_tokens = (metrics.input_tokens or 0) + int(inp)
                if out is not None:
                    metrics.output_tokens = (metrics.output_tokens or 0) + int(out)

    # Session-level token economics (token-type split, AIU cost, context, productivity).
    econ = extract_economics(events)
    metrics.input_tokens_noncached = econ.input_tokens_noncached
    metrics.cache_read_tokens = econ.cache_read_tokens
    metrics.cache_write_tokens = econ.cache_write_tokens
    metrics.reasoning_tokens = econ.reasoning_tokens
    metrics.aiu = econ.aiu
    metrics.aiu_by_type = econ.aiu_by_type
    metrics.api_duration_ms = econ.api_duration_ms
    metrics.n_requests = econ.n_requests
    metrics.system_tokens = econ.system_tokens
    metrics.tool_definitions_tokens = econ.tool_definitions_tokens
    metrics.conversation_tokens = econ.conversation_tokens
    metrics.context_tokens = econ.context_tokens
    metrics.peak_context_tokens = econ.peak_context_tokens
    metrics.n_compactions = econ.n_compactions
    metrics.n_truncations = econ.n_truncations
    metrics.compaction_aiu = econ.compaction_aiu
    metrics.files_modified = econ.files_modified
    metrics.lines_added = econ.lines_added
    metrics.lines_removed = econ.lines_removed

    if econ.total_tokens is not None:
        # session.shutdown is authoritative when present.
        metrics.input_tokens = econ.input_tokens_total
        metrics.output_tokens = econ.output_tokens
        metrics.total_tokens = econ.total_tokens
    elif metrics.input_tokens is not None or metrics.output_tokens is not None:
        metrics.total_tokens = (metrics.input_tokens or 0) + (metrics.output_tokens or 0)

    # De-duplicate models while preserving order.
    metrics.models = list(dict.fromkeys(models))

    if len(timestamps) >= 2:
        metrics.duration_s = (max(timestamps) - min(timestamps)).total_seconds()

    return metrics
