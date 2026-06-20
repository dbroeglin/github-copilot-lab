"""Tests for the temporal phase-level analysis (Bai et al. Finding #6)."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from copilot_experiments.analysis import _phase_bounds, analyze_events
from copilot_experiments.render import render_session_analysis


def _turn_events(turn_no: int, *, out: int, tools: int) -> list[dict]:
    """One assistant turn emitting ``out`` output tokens and ``tools`` tool calls."""
    base = f"2026-01-01T00:00:{turn_no:02d}"
    requests = [{"toolCallId": f"c{turn_no}-{i}", "name": "view"} for i in range(tools)]
    events: list[dict] = [
        {
            "type": "assistant.turn_start",
            "timestamp": f"{base}.000Z",
            "data": {"turnId": str(turn_no)},
        },
        {
            "type": "assistant.message",
            "timestamp": f"{base}.100Z",
            "data": {"model": "m", "content": "", "outputTokens": out, "toolRequests": requests},
        },
    ]
    for i in range(tools):
        cid = f"c{turn_no}-{i}"
        events.append(
            {
                "type": "tool.execution_start",
                "timestamp": f"{base}.200Z",
                "data": {"toolCallId": cid, "toolName": "view", "turnId": str(turn_no)},
            }
        )
        events.append(
            {
                "type": "tool.execution_complete",
                "timestamp": f"{base}.300Z",
                "data": {"toolCallId": cid, "success": True},
            }
        )
    events.append(
        {
            "type": "assistant.turn_end",
            "timestamp": f"{base}.500Z",
            "data": {"turnId": str(turn_no)},
        }
    )
    return events


def _session(specs: list[tuple[int, int]]) -> list[dict]:
    """Build a session from ``(output_tokens, n_tools)`` specs, one per turn."""
    events: list[dict] = [
        {
            "type": "session.start",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "data": {"sessionId": "s", "selectedModel": "m"},
        },
        {
            "type": "user.message",
            "timestamp": "2026-01-01T00:00:00.500Z",
            "data": {"content": "go"},
        },
    ]
    for i, (out, tools) in enumerate(specs, start=1):
        events.extend(_turn_events(i, out=out, tools=tools))
    return events


def test_phase_bounds_even_split():
    assert _phase_bounds(10) == [(0, 2), (2, 4), (4, 6), (6, 8), (8, 10)]


def test_phase_bounds_uneven_split():
    # n=12, k=5 -> first two groups get the extra turn (numpy.array_split semantics).
    assert _phase_bounds(12) == [(0, 3), (3, 6), (6, 8), (8, 10), (10, 12)]


def test_phase_bounds_too_short_returns_empty():
    assert _phase_bounds(4) == []
    assert _phase_bounds(0) == []


def test_short_session_has_no_phases():
    a = analyze_events(_session([(10, 1)] * 4))
    assert a.phases == []


def test_ten_turn_session_phase_distribution():
    # Tool-heavy + low output early; generation-heavy late (Finding #6 shape).
    specs = [
        (10, 2),
        (20, 2),  # early
        (30, 1),
        (40, 1),  # early_mid
        (50, 0),
        (60, 0),  # mid
        (70, 0),
        (80, 0),  # later_mid
        (90, 0),
        (100, 0),  # later
    ]
    a = analyze_events(_session(specs))

    assert [p.name for p in a.phases] == ["early", "early_mid", "mid", "later_mid", "later"]
    assert all(p.n_turns == 2 for p in a.phases)
    assert a.phases[0].turn_from == 1 and a.phases[0].turn_to == 2
    assert a.phases[-1].turn_from == 9 and a.phases[-1].turn_to == 10

    # Output share rises from early to later, and sums to ~1.0.
    shares = [p.output_share for p in a.phases]
    assert all(s is not None for s in shares)
    assert abs(sum(shares) - 1.0) < 1e-9
    assert shares[-1] > shares[0]

    # Tool activity is front-loaded.
    assert a.phases[0].n_tool_calls > a.phases[-1].n_tool_calls
    assert a.phases[0].n_tool_calls == 4
    assert a.phases[-1].n_tool_calls == 0

    # Output tokens aggregate per phase.
    assert a.phases[0].output_tokens == 30
    assert a.phases[-1].output_tokens == 190


def test_render_includes_phase_table():
    a = analyze_events(_session([(10 * i, 1 if i <= 3 else 0) for i in range(1, 11)]))
    console = Console(file=StringIO(), width=100, no_color=True)
    render_session_analysis(a, console)
    out = console.file.getvalue()
    assert "Phases (temporal)" in out
    assert "early_mid" in out
    assert "later" in out
