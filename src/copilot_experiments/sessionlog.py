"""Locate and parse Copilot CLI session logs (``events.jsonl``)."""

from __future__ import annotations

import datetime as _dt
import json
import shutil
from pathlib import Path
from typing import Any

from .models import Metrics


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
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
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
        elif etype == "tool.execution_complete":
            metrics.n_tool_calls += 1
            if data.get("success") is False:
                metrics.n_tool_failures += 1
            model = data.get("model")
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

    if metrics.input_tokens is not None or metrics.output_tokens is not None:
        metrics.total_tokens = (metrics.input_tokens or 0) + (metrics.output_tokens or 0)

    # De-duplicate models while preserving order.
    metrics.models = list(dict.fromkeys(models))

    if len(timestamps) >= 2:
        metrics.duration_s = (max(timestamps) - min(timestamps)).total_seconds()

    return metrics
