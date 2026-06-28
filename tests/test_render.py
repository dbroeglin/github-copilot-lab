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


# --------------------------------------------------------------------------- #
# render_session_analysis: full-overview rendering incl. the multi-model table
# --------------------------------------------------------------------------- #


def _render_to_text(analysis) -> str:
    from io import StringIO

    from rich.console import Console

    from copilot_experiments.render import render_session_analysis

    buf = StringIO()
    console = Console(file=buf, width=200, force_terminal=False, color_system=None)
    render_session_analysis(analysis, console, title="Test")
    return buf.getvalue()


def test_render_session_analysis_includes_per_model_table_when_multimodel():
    from copilot_experiments.models import ModelMetric, SessionAnalysis, TokenEconomics, TurnSummary

    econ = TokenEconomics(
        input_tokens_noncached=100,
        cache_read_tokens=900,
        cache_write_tokens=0,
        output_tokens=50,
        input_tokens_total=1000,
        total_tokens=1050,
        aiu=2.5,
        n_requests=3,
        api_duration_ms=1500,
        aiu_by_type={"input": 1.0, "cache_read": 0.5, "cache_write": 0.0, "output": 1.0},
        model_metrics=[
            ModelMetric(model="claude-opus-4.7", requests=2, input_tokens=600, output_tokens=30),
            ModelMetric(model="gpt-5.5", requests=1, input_tokens=400, output_tokens=20),
        ],
    )
    analysis = SessionAnalysis(
        session_id="s1",
        models=["claude-opus-4.7", "gpt-5.5"],
        n_turns=1,
        turns=[TurnSummary(turn_no=1, started_at="2026-01-01T00:00:00Z")],
        economics=econ,
    )
    out = _render_to_text(analysis)
    assert "Per model" in out
    assert "claude-opus-4.7" in out
    assert "gpt-5.5" in out
    assert "Cost (AIU)" in out


def test_render_session_analysis_minimal_without_economics():
    from copilot_experiments.models import SessionAnalysis, TurnSummary

    analysis = SessionAnalysis(
        session_id="s2",
        models=["gpt-5.5"],
        n_turns=1,
        turns=[TurnSummary(turn_no=1, started_at="2026-01-01T00:00:00Z")],
        warnings=["heads up"],
    )
    out = _render_to_text(analysis)
    # No shutdown economics -> the Cost table is omitted, but warnings still render.
    assert "Cost (AIU)" not in out
    assert "heads up" in out


# --------------------------------------------------------------------------- #
# LiveEventFormatter: remaining event branches
# --------------------------------------------------------------------------- #


def test_live_formatter_session_end_and_turn_end():
    fmt = LiveEventFormatter()
    # turn_end before any turn -> nothing to show.
    assert fmt.format(_ev("assistant.turn_end")) is None
    fmt.format(_ev("assistant.turn_start"))
    assert fmt.format(_ev("assistant.turn_end")) == "[turn 1] end"
    assert fmt.format(_ev("session.end")) == "[session] end"


def test_live_formatter_empty_assistant_message_is_skipped():
    fmt = LiveEventFormatter()
    assert fmt.format(_ev("assistant.message", content="")) is None


def test_live_formatter_non_dict_event_returns_raw():
    fmt = LiveEventFormatter()
    assert fmt.format("[1, 2, 3]") == "[1, 2, 3]"


def test_live_formatter_warning_branch():
    fmt = LiveEventFormatter()
    assert fmt.format(_ev("session.warning", message="careful")) == "[warn] careful"
