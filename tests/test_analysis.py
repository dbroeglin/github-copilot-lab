"""Tests for the session-log analysis layer and its Rich rendering."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from copilot_experiments.analysis import analyze_events
from copilot_experiments.render import render_session_analysis


def _events() -> list[dict]:
    """A representative, real-schema multi-turn session log."""
    return [
        {
            "type": "session.start",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "data": {
                "sessionId": "sess-1",
                "producer": "copilot-agent",
                "copilotVersion": "1.2.3",
                "selectedModel": "claude-opus-4.8",
                "reasoningEffort": "high",
                "startTime": "2026-01-01T00:00:00.000Z",
                "context": {"repository": "acme/widgets", "branch": "main", "cwd": "/w"},
            },
        },
        {
            "type": "user.message",
            "timestamp": "2026-01-01T00:00:01.000Z",
            "data": {"content": "Fix the bug please"},
        },
        # Turn 0: a successful view.
        {
            "type": "assistant.turn_start",
            "timestamp": "2026-01-01T00:00:01.100Z",
            "data": {"turnId": "0"},
        },
        {
            "type": "assistant.message",
            "timestamp": "2026-01-01T00:00:01.500Z",
            "data": {
                "model": "claude-opus-4.8",
                "content": "Looking at the code.",
                "outputTokens": 100,
                "toolRequests": [{"toolCallId": "c1", "name": "view"}],
            },
        },
        {
            "type": "tool.execution_start",
            "timestamp": "2026-01-01T00:00:01.600Z",
            "data": {
                "toolCallId": "c1",
                "toolName": "view",
                "model": "claude-opus-4.8",
                "turnId": "0",
            },
        },
        {
            "type": "tool.execution_complete",
            "timestamp": "2026-01-01T00:00:01.800Z",
            "data": {"toolCallId": "c1", "success": True},
        },
        {
            "type": "assistant.turn_end",
            "timestamp": "2026-01-01T00:00:02.000Z",
            "data": {"turnId": "0"},
        },
        # Turn 1: a failing powershell call.
        {
            "type": "assistant.turn_start",
            "timestamp": "2026-01-01T00:00:02.100Z",
            "data": {"turnId": "1"},
        },
        {
            "type": "assistant.message",
            "timestamp": "2026-01-01T00:00:02.300Z",
            "data": {
                "model": "claude-opus-4.8",
                "content": "Running tests.",
                "outputTokens": 50,
                "toolRequests": [{"toolCallId": "c2", "name": "powershell"}],
            },
        },
        {
            "type": "tool.execution_start",
            "timestamp": "2026-01-01T00:00:02.400Z",
            "data": {
                "toolCallId": "c2",
                "toolName": "powershell",
                "model": "claude-opus-4.8",
                "turnId": "1",
            },
        },
        {
            "type": "tool.execution_complete",
            "timestamp": "2026-01-01T00:00:02.600Z",
            "data": {"toolCallId": "c2", "success": False},
        },
        {"type": "hook.start", "timestamp": "2026-01-01T00:00:02.650Z", "data": {}},
        {"type": "hook.end", "timestamp": "2026-01-01T00:00:02.660Z", "data": {}},
        {
            "type": "session.warning",
            "timestamp": "2026-01-01T00:00:02.700Z",
            "data": {"message": "heads up"},
        },
        {
            "type": "assistant.turn_end",
            "timestamp": "2026-01-01T00:00:03.000Z",
            "data": {"turnId": "1"},
        },
    ]


def _otel_records() -> list[dict]:
    return [
        {
            "type": "span",
            "name": "chat claude-opus-4.8",
            "startTime": [1767225601, 100_000_000],
            "endTime": [1767225601, 900_000_000],
            "attributes": {
                "gen_ai.operation.name": "chat",
                "gen_ai.request.model": "claude-opus-4.8",
                "gen_ai.response.model": "claude-opus-4.8",
                "gen_ai.usage.input_tokens": 1000,
                "gen_ai.usage.cache_creation_input_tokens": 200,
                "gen_ai.usage.output_tokens": 100,
                "github.copilot.nano_aiu": 500_000_000,
                "github.copilot.server_duration": 750,
                "github.copilot.turn_id": "0",
            },
            "events": [
                {
                    "name": "github.copilot.session.usage_info",
                    "attributes": {
                        "github.copilot.current_tokens": 900,
                        "github.copilot.token_limit": 2000,
                    },
                }
            ],
        },
        {
            "type": "span",
            "name": "chat claude-opus-4.8",
            "startTime": [1767225602, 100_000_000],
            "endTime": [1767225602, 600_000_000],
            "attributes": {
                "gen_ai.operation.name": "chat",
                "gen_ai.request.model": "claude-opus-4.8",
                "gen_ai.response.model": "claude-opus-4.8",
                "gen_ai.usage.input_tokens": 1200,
                "gen_ai.usage.cache_creation_input_tokens": 50,
                "gen_ai.usage.output_tokens": 50,
                "github.copilot.nano_aiu": 250_000_000,
                "github.copilot.server_duration": 450,
                "github.copilot.turn_id": 1,
            },
        },
    ]


def test_analyze_header_fields():
    a = analyze_events(_events())
    assert a.session_id == "sess-1"
    assert a.copilot_version == "1.2.3"
    assert a.reasoning_effort == "high"
    assert a.models == ["claude-opus-4.8"]
    assert a.repository == "acme/widgets"
    assert a.branch == "main"
    assert a.started_at == "2026-01-01T00:00:00.000Z"
    assert a.duration_s == 3.0


def test_analyze_totals():
    a = analyze_events(_events())
    assert a.n_turns == 2
    assert a.n_user_messages == 1
    assert a.n_assistant_messages == 2
    assert a.n_tool_calls == 2
    assert a.n_tool_failures == 1
    assert a.n_warnings == 1
    assert a.n_hooks == 1
    assert a.warnings == ["heads up"]


def test_analyze_tokens():
    a = analyze_events(_events())
    assert a.output_tokens == 150
    assert a.input_tokens is None
    assert a.total_tokens == 150


def test_analyze_tool_histogram_correlates_failures():
    a = analyze_events(_events())
    by_name = {t.name: t for t in a.tools}
    assert by_name["view"].calls == 1 and by_name["view"].failures == 0
    assert by_name["powershell"].calls == 1 and by_name["powershell"].failures == 1


def test_analyze_timeline():
    a = analyze_events(_events())
    assert [t.turn_no for t in a.turns] == [1, 2]
    assert a.turns[0].tools == ["view"]
    assert a.turns[0].output_tokens == 100
    assert a.turns[0].text_preview.startswith("Looking at the code")
    assert a.turns[0].duration_s == 0.9
    assert a.turns[1].tools == ["powershell"]


def test_analyze_enriches_llm_calls_from_otel():
    a = analyze_events(_events(), _otel_records())
    assert len(a.llm_calls) == 2
    assert a.llm_calls[0].input_tokens == 1000
    assert a.llm_calls[0].cache_creation_input_tokens == 200
    assert a.llm_calls[0].aiu == 0.5
    assert a.llm_calls[0].server_duration_ms == 750
    assert a.llm_calls[0].current_tokens == 900
    assert a.llm_calls[1].turn_id == "1"
    assert a.turns[0].input_tokens == 1000
    assert a.turns[0].cache_creation_input_tokens == 200
    assert a.turns[0].aiu == 0.5
    assert a.turns[1].input_tokens == 1200
    assert a.input_tokens == 2200
    assert a.output_tokens == 150
    assert a.total_tokens == 2350
    assert a.economics.cache_write_tokens == 250
    assert a.economics.aiu == 0.75
    assert a.economics.api_duration_ms == 1200
    assert a.economics.n_requests == 2


def test_analyze_empty():
    a = analyze_events([])
    assert a.n_turns == 0
    assert a.tools == []
    assert a.duration_s is None
    assert a.total_tokens is None


def test_render_smoke():
    a = analyze_events(_events())
    buf = StringIO()
    console = Console(file=buf, width=100, force_terminal=False)
    render_session_analysis(a, console, title="my-trial", max_turns=10)
    out = buf.getvalue()
    for needle in ("my-trial", "Totals", "Tool usage", "Timeline", "powershell", "Warnings"):
        assert needle in out


def test_render_includes_otel_llm_calls():
    a = analyze_events(_events(), _otel_records())
    buf = StringIO()
    console = Console(file=buf, width=140, force_terminal=False)
    render_session_analysis(a, console, title="with-otel", max_turns=10)
    out = buf.getvalue()
    assert "LLM calls (OTel)" in out
    assert "cache write" in out
    assert "0.500" in out
