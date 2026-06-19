"""Tests for parsing Copilot session events into metrics."""

from __future__ import annotations

from copilot_experiments.sessionlog import parse_metrics


def _events():
    return [
        {"type": "session.start", "timestamp": "2026-01-01T00:00:00.000Z", "data": {}},
        {
            "type": "session.model_change",
            "timestamp": "2026-01-01T00:00:00.100Z",
            "data": {"newModel": "gpt-5.2"},
        },
        {"type": "assistant.turn_start", "timestamp": "2026-01-01T00:00:00.200Z", "data": {}},
        {
            "type": "assistant.message",
            "timestamp": "2026-01-01T00:00:00.500Z",
            "data": {"text": "hi", "model": "gpt-5.2"},
        },
        {
            "type": "tool.execution_complete",
            "timestamp": "2026-01-01T00:00:00.800Z",
            "data": {"success": True},
        },
        {
            "type": "tool.execution_complete",
            "timestamp": "2026-01-01T00:00:01.000Z",
            "data": {"success": False},
        },
        {"type": "session.warning", "timestamp": "2026-01-01T00:00:01.100Z", "data": {}},
        {"type": "assistant.turn_end", "timestamp": "2026-01-01T00:00:02.000Z", "data": {}},
    ]


def test_parse_metrics_counts():
    m = parse_metrics(_events())
    assert m.n_turns == 1
    assert m.n_assistant_messages == 1
    assert m.n_tool_calls == 2
    assert m.n_tool_failures == 1
    assert m.n_warnings == 1
    assert "gpt-5.2" in m.models


def test_parse_metrics_duration():
    m = parse_metrics(_events())
    assert m.duration_s is not None
    assert m.duration_s == 2.0


def test_parse_metrics_empty():
    m = parse_metrics([])
    assert m.n_turns == 0
    assert m.duration_s is None
