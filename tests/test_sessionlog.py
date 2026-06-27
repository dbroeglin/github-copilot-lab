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


# --------------------------------------------------------------------------- #
# load_events / copy_events filesystem helpers
# --------------------------------------------------------------------------- #


def test_load_events_skips_blank_and_invalid_lines(tmp_path):
    from copilot_experiments.sessionlog import load_events

    path = tmp_path / "events.jsonl"
    path.write_text(
        '{"type": "session.start"}\n\n   \nnot-json\n{"type": "user.message"}\n',
        encoding="utf-8",
    )
    events = load_events(path)
    assert [e["type"] for e in events] == ["session.start", "user.message"]


def test_load_events_missing_file_returns_empty(tmp_path):
    from copilot_experiments.sessionlog import load_events

    assert load_events(tmp_path / "nope.jsonl") == []


def test_copy_events_roundtrip_with_base(tmp_path):
    from copilot_experiments.sessionlog import copy_events, events_path

    base = tmp_path / "state"
    src = events_path("sess-1", base)
    src.parent.mkdir(parents=True)
    src.write_text('{"type": "session.start"}\n', encoding="utf-8")

    dest = tmp_path / "out" / "events.jsonl"
    assert copy_events("sess-1", dest, base) is True
    assert dest.read_text(encoding="utf-8") == '{"type": "session.start"}\n'


def test_copy_events_missing_source_returns_false(tmp_path):
    from copilot_experiments.sessionlog import copy_events

    dest = tmp_path / "out" / "events.jsonl"
    assert copy_events("absent", dest, tmp_path / "state") is False
    assert not dest.exists()


# --------------------------------------------------------------------------- #
# extract_economics: compaction_start peak tracking (no shutdown)
# --------------------------------------------------------------------------- #


def test_compaction_start_tracks_peak_without_shutdown():
    from copilot_experiments.sessionlog import extract_economics

    events = [
        {
            "type": "session.compaction_start",
            "data": {
                "systemTokens": 1000,
                "conversationTokens": 8000,
                "toolDefinitionsTokens": 500,
            },
        },
    ]
    econ = extract_economics(events)
    assert econ.total_tokens is None  # no shutdown -> no authoritative totals
    assert econ.peak_context_tokens == 9500  # 1000 + 8000 + 500
