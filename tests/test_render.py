"""Tests for the live (per-event) verbose formatter."""

from __future__ import annotations

import json

from copilot_experiments.render import LiveEventFormatter


def _ev(etype: str, **data: object) -> str:
    return json.dumps({"type": etype, "timestamp": "2026-01-01T00:00:00Z", "data": data})


def test_live_formatter_summarizes_known_events():
    fmt = LiveEventFormatter()
    assert fmt.format(_ev("session.start", selectedModel="gpt-x", reasoningEffort="high")) == (
        "[session] start model=gpt-x effort=high"
    )
    assert fmt.format(_ev("user.message", content="do the thing")) == "[user] do the thing"
    assert fmt.format(_ev("assistant.turn_start", turnId="0")) == "[turn 1] start"
    assert fmt.format(_ev("assistant.message", content="working", outputTokens=42)) == (
        "[asst] working (42 tok)"
    )


def test_live_formatter_correlates_tool_calls_by_id():
    fmt = LiveEventFormatter()
    assert fmt.format(_ev("tool.execution_start", toolName="edit", toolCallId="c1")) == (
        "[tool] edit start"
    )
    # Completion carries no toolName -> must be recovered from the toolCallId.
    assert fmt.format(_ev("tool.execution_complete", toolCallId="c1", success=True)) == (
        "[tool] edit ok"
    )
    assert fmt.format(_ev("tool.execution_complete", toolCallId="c1", success=False)) == (
        "[tool] edit FAILED"
    )


def test_live_formatter_skips_noise_but_surfaces_errors():
    fmt = LiveEventFormatter()
    assert fmt.format(_ev("session.mcp_server_status_changed", name="x")) is None
    assert fmt.format("   ") is None
    assert fmt.format(_ev("session.error", message="boom")) == "[session.error] boom"


def test_live_formatter_falls_back_to_raw_for_non_json():
    fmt = LiveEventFormatter()
    assert fmt.format("not json at all") == "not json at all"
