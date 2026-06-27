"""Unit tests for the analysis internals: ATIF-trajectory parsing, the events+OTel merge, and
the OTel attribute/time decoders.

These use **synthetic, hand-controlled** inputs (not captured artifacts). The ATIF
``trajectory.json`` is produced by this package's own Pier converter, so real trajectories can't
serve as authoritative golden data — instead we drive ``analyze_trajectory`` with crafted inputs
and assert the parsing/aggregation logic directly. Real, externally-produced ``events.jsonl`` /
``copilot-otel.jsonl`` ground truth lives in ``test_real_sessions.py``.
"""

from __future__ import annotations

import datetime as _dt

from copilot_experiments.analysis import (
    _otel_attr_value,
    _otel_attrs,
    _otel_value,
    _parse_otel_time,
    analyze_events,
    analyze_trajectory,
    llm_calls_from_otel,
)

# --------------------------------------------------------------------------- #
# analyze_trajectory (synthetic ATIF)
# --------------------------------------------------------------------------- #


def _agent_step(
    *,
    ts: str,
    message: str = "Tool call",
    tools: list[tuple[str, str]] | None = None,
    completion_tokens: int | None = None,
    failed_call_ids: list[str] | None = None,
    model: str = "claude-opus-4.7",
) -> dict:
    """Build one ``source="agent"`` ATIF step."""
    tool_calls = [{"tool_call_id": cid, "function_name": name} for name, cid in (tools or [])]
    results = []
    for _name, cid in tools or []:
        content = '{"code": "failure"}' if failed_call_ids and cid in failed_call_ids else "ok"
        results.append({"source_call_id": cid, "content": content})
    step: dict = {
        "timestamp": ts,
        "source": "agent",
        "model_name": model,
        "message": message,
        "tool_calls": tool_calls,
        "observation": {"results": results},
    }
    if completion_tokens is not None:
        step["metrics"] = {"completion_tokens": completion_tokens}
    return step


def _trajectory(*, steps: list[dict], final_metrics: dict | None = None) -> dict:
    traj: dict = {
        "schema_version": "ATIF-v1.7",
        "session_id": "sess-xyz",
        "agent": {"name": "copilot-cli", "version": "1.0.65", "model_name": "claude-opus-4.7"},
        "steps": steps,
    }
    if final_metrics is not None:
        traj["final_metrics"] = final_metrics
    return traj


def _full_trajectory() -> dict:
    return _trajectory(
        steps=[
            {"timestamp": "2026-01-01T00:00:00.000Z", "source": "user", "message": "fix it"},
            _agent_step(
                ts="2026-01-01T00:00:01.000Z",
                message="reading the file",
                tools=[("view", "c1"), ("glob", "c2")],
                completion_tokens=40,
            ),
            _agent_step(
                ts="2026-01-01T00:00:03.000Z",
                tools=[("bash", "c3")],
                completion_tokens=20,
                failed_call_ids=["c3"],
            ),
            _agent_step(
                ts="2026-01-01T00:00:05.000Z",
                message="done",
                tools=[("bash", "c4")],
                completion_tokens=10,
            ),
        ],
        final_metrics={
            "total_prompt_tokens": 1000,
            "total_completion_tokens": 70,
            "total_cached_tokens": 800,
            "extra": {
                "aiu": 2.5,
                "reasoning_tokens": 12,
                "peak_context_tokens": 5000,
                "summarization_count": 1,
            },
        },
    )


def test_trajectory_basic_counts_and_metadata():
    a = analyze_trajectory(_full_trajectory())
    assert a.producer == "ATIF trajectory"
    assert a.session_id == "sess-xyz"
    assert a.copilot_version == "1.0.65"
    assert a.models == ["claude-opus-4.7"]
    assert a.n_events == 4  # one user + three agent steps
    assert a.n_user_messages == 1
    assert a.n_assistant_messages == 3
    assert a.n_turns == 3


def test_trajectory_tool_histogram_and_failures():
    a = analyze_trajectory(_full_trajectory())
    assert a.n_tool_calls == 4
    assert a.n_tool_failures == 1
    by_name = {t.name: t for t in a.tools}
    assert by_name["bash"].calls == 2
    assert by_name["bash"].failures == 1
    assert by_name["view"].calls == 1
    # Sorted by descending calls then name: bash (2) first.
    assert a.tools[0].name == "bash"


def test_trajectory_final_metrics_drive_economics():
    a = analyze_trajectory(_full_trajectory())
    assert a.input_tokens == 1000
    assert a.output_tokens == 70
    assert a.total_tokens == 1070
    assert a.economics.input_tokens_total == 1000
    assert a.economics.input_tokens_noncached == 1000
    assert a.economics.output_tokens == 70
    assert a.economics.cache_read_tokens == 800
    assert a.economics.aiu == 2.5
    assert a.economics.reasoning_tokens == 12
    assert a.economics.peak_context_tokens == 5000
    assert a.economics.n_compactions == 1


def test_trajectory_duration_from_timestamps():
    a = analyze_trajectory(_full_trajectory())
    assert a.duration_s == 5.0
    assert a.started_at is not None and a.started_at.endswith("Z")
    assert a.finished_at is not None and a.finished_at.endswith("Z")


def test_trajectory_falls_back_to_summed_output_without_final_completion():
    # final_metrics present but no total_completion_tokens -> sum step completion_tokens.
    traj = _trajectory(
        steps=[
            {"timestamp": "2026-01-01T00:00:00Z", "source": "user", "message": "go"},
            _agent_step(ts="2026-01-01T00:00:01Z", tools=[("view", "c1")], completion_tokens=15),
            _agent_step(ts="2026-01-01T00:00:02Z", tools=[("bash", "c2")], completion_tokens=25),
        ],
        final_metrics={"total_prompt_tokens": 500},
    )
    a = analyze_trajectory(traj)
    assert a.input_tokens == 500
    assert a.output_tokens == 40  # 15 + 25
    assert a.total_tokens == 540


def test_trajectory_without_final_metrics_uses_summed_output():
    traj = _trajectory(
        steps=[
            {"timestamp": "2026-01-01T00:00:00Z", "source": "user", "message": "go"},
            _agent_step(ts="2026-01-01T00:00:01Z", tools=[("view", "c1")], completion_tokens=7),
        ]
    )
    a = analyze_trajectory(traj)
    assert a.output_tokens == 7
    assert a.economics.output_tokens == 7


def test_trajectory_permission_denied_marker_counts_as_failure():
    traj = _trajectory(
        steps=[
            _agent_step(ts="2026-01-01T00:00:01Z", tools=[("bash", "c1")]),
        ]
    )
    # Override the observation to use a "permission denied" style marker.
    traj["steps"][0]["observation"]["results"][0]["content"] = "Error: Permission denied"
    a = analyze_trajectory(traj)
    assert a.n_tool_failures == 1


def test_trajectory_tool_without_function_name_is_unknown():
    traj = _trajectory(
        steps=[
            {
                "timestamp": "2026-01-01T00:00:01Z",
                "source": "agent",
                "tool_calls": [{"tool_call_id": "c1"}],  # no function_name
                "observation": {"results": []},
            }
        ]
    )
    a = analyze_trajectory(traj)
    assert a.tools[0].name == "unknown"
    assert a.n_tool_calls == 1


def test_trajectory_handles_malformed_input_gracefully():
    # steps not a list; agent not a dict.
    a = analyze_trajectory({"agent": "nope", "steps": "nope"})
    assert a.n_events == 0
    assert a.n_turns == 0
    assert a.duration_s is None
    # Empty dict.
    b = analyze_trajectory({})
    assert b.n_events == 0
    assert b.models == []


def test_trajectory_skips_non_dict_steps():
    traj = _trajectory(
        steps=[
            "garbage",  # type: ignore[list-item]
            {"timestamp": "2026-01-01T00:00:01Z", "source": "user", "message": "go"},
            _agent_step(ts="2026-01-01T00:00:02Z", tools=[("view", "c1")], completion_tokens=5),
        ]
    )
    a = analyze_trajectory(traj)
    assert a.n_user_messages == 1
    assert a.n_assistant_messages == 1


# --------------------------------------------------------------------------- #
# _apply_otel_records merge behavior
# --------------------------------------------------------------------------- #


def _otel_chat_span(turn_id: str, *, in_tok: int, out_tok: int, cache_read: int, nano: int) -> dict:
    return {
        "type": "span",
        "name": "chat claude-opus-4.7",
        "startTime": [1782573865, 0],
        "endTime": [1782573866, 0],
        "attributes": {
            "gen_ai.operation.name": "chat",
            "gen_ai.request.model": "claude-opus-4.7",
            "gen_ai.usage.input_tokens": in_tok,
            "gen_ai.usage.output_tokens": out_tok,
            "gen_ai.usage.cache_read.input_tokens": cache_read,
            "github.copilot.nano_aiu": nano,
            "github.copilot.turn_id": turn_id,
            "github.copilot.server_duration": 900,
        },
    }


def _events_with_turn(turn_id: str, *, with_shutdown: bool) -> list[dict]:
    events = [
        {"type": "session.start", "timestamp": "2026-01-01T00:00:00Z", "data": {}},
        {
            "type": "assistant.turn_start",
            "timestamp": "2026-01-01T00:00:01Z",
            "data": {"turnId": turn_id},
        },
        {
            "type": "assistant.message",
            "timestamp": "2026-01-01T00:00:01.2Z",
            "data": {"model": "claude-opus-4.7", "content": "hi"},
        },
        {"type": "assistant.turn_end", "timestamp": "2026-01-01T00:00:02Z", "data": {}},
    ]
    if with_shutdown:
        events.append(
            {
                "type": "session.shutdown",
                "timestamp": "2026-01-01T00:00:03Z",
                "data": {
                    "tokenDetails": {
                        "input": {"tokenCount": 100},
                        "cache_read": {"tokenCount": 900},
                        "output": {"tokenCount": 50},
                    },
                    "totalNanoAiu": 1_000_000_000,
                },
            }
        )
    return events


def test_merge_shutdown_stays_authoritative_but_turns_enriched():
    events = _events_with_turn("0", with_shutdown=True)
    otel = [_otel_chat_span("0", in_tok=999, out_tok=9, cache_read=888, nano=5_000_000_000)]
    a = analyze_events(events, otel)
    # Aggregate economics come from shutdown, NOT OTel.
    assert a.total_tokens == 100 + 900 + 50
    assert a.economics.aiu == 1.0
    # llm_calls populated from OTel.
    assert len(a.llm_calls) == 1
    # The matching turn is enriched with OTel per-call numbers.
    turn = {t.turn_id: t for t in a.turns}["0"]
    assert turn.input_tokens == 999
    assert turn.cache_read_input_tokens == 888
    assert turn.aiu == 5.0
    assert turn.api_duration_ms == 900


def test_merge_otel_reconstructs_totals_without_shutdown():
    events = _events_with_turn("0", with_shutdown=False)
    otel = [
        _otel_chat_span("0", in_tok=500, out_tok=20, cache_read=400, nano=2_000_000_000),
        _otel_chat_span("0", in_tok=600, out_tok=30, cache_read=450, nano=3_000_000_000),
    ]
    a = analyze_events(events, otel)
    # No shutdown -> OTel reconstructs aggregate economics.
    assert a.input_tokens == 1100
    assert a.output_tokens == 50
    assert a.total_tokens == 1150
    assert a.economics.cache_read_tokens == 850
    assert a.economics.aiu == 5.0
    assert a.economics.n_requests == 2
    assert a.economics.api_duration_ms == 1800


def test_merge_unmatched_turn_id_is_skipped():
    events = _events_with_turn("0", with_shutdown=False)
    otel = [_otel_chat_span("99", in_tok=10, out_tok=1, cache_read=0, nano=1_000_000_000)]
    a = analyze_events(events, otel)
    # No crash; the call is still recorded and totals reconstructed.
    assert len(a.llm_calls) == 1
    assert a.input_tokens == 10
    # Turn "0" got no enrichment (its input stays None).
    assert {t.turn_id: t for t in a.turns}["0"].input_tokens is None


def test_merge_no_otel_calls_leaves_analysis_untouched():
    events = _events_with_turn("0", with_shutdown=True)
    a = analyze_events(events, [{"type": "span", "name": "execute_tool view", "attributes": {}}])
    assert a.llm_calls == []
    assert a.total_tokens == 100 + 900 + 50  # still from shutdown


# --------------------------------------------------------------------------- #
# OTel attribute / value / time decoders (alternate encodings)
# --------------------------------------------------------------------------- #


def test_otel_attrs_from_dict_form():
    assert _otel_attrs({"a": 1, "b": "x"}) == {"a": 1, "b": "x"}


def test_otel_attrs_from_otlp_list_form():
    raw = [
        {"key": "gen_ai.usage.input_tokens", "value": {"intValue": "42"}},
        {"key": "model", "value": {"stringValue": "gpt-5.5"}},
    ]
    assert _otel_attrs(raw) == {"gen_ai.usage.input_tokens": "42", "model": "gpt-5.5"}


def test_otel_attrs_other_returns_empty():
    assert _otel_attrs("nope") == {}
    assert _otel_attrs(None) == {}


def test_otel_value_typed_scalars():
    assert _otel_value({"stringValue": "s"}) == "s"
    assert _otel_value({"intValue": "5"}) == "5"
    assert _otel_value({"doubleValue": 1.5}) == 1.5
    assert _otel_value({"boolValue": True}) is True
    assert _otel_value(7) == 7  # passthrough non-dict


def test_otel_value_array_and_kvlist():
    arr = {"arrayValue": {"values": [{"stringValue": "a"}, {"stringValue": "b"}]}}
    assert _otel_value(arr) == ["a", "b"]
    kv = {"kvlistValue": {"values": [{"key": "k", "value": {"intValue": "9"}}]}}
    assert _otel_value(kv) == {"k": "9"}


def test_otel_attr_value_flat_and_nested():
    # Flat dotted key present directly.
    assert _otel_attr_value({"a.b.c": 5}, "a.b.c") == 5
    # Nested dict under a dotted prefix.
    assert _otel_attr_value({"a.b": {"c": 7}}, "a.b.c") == 7
    # Missing.
    assert _otel_attr_value({}, "a.b.c") is None


def test_parse_otel_time_iso_string():
    t = _parse_otel_time("2026-01-01T00:00:00Z")
    assert t == _dt.datetime(2026, 1, 1, tzinfo=_dt.UTC)


def test_parse_otel_time_seconds_nanos_array():
    t = _parse_otel_time([1782573865, 500_000_000])
    assert t is not None
    assert t.tzinfo is not None
    # 0.5s of nanos -> 500000 microseconds.
    assert t.microsecond == 500_000


def test_parse_otel_time_epoch_units():
    base = _dt.datetime.fromtimestamp(1782573865, tz=_dt.UTC)
    assert _parse_otel_time(1782573865).replace(microsecond=0) == base  # seconds
    assert _parse_otel_time(1782573865000).replace(microsecond=0) == base  # millis
    assert _parse_otel_time(1782573865000000000).replace(microsecond=0) == base  # nanos


def test_parse_otel_time_invalid():
    assert _parse_otel_time("not-a-time") is None
    assert _parse_otel_time(None) is None


def test_llm_calls_from_otel_with_otlp_list_attributes():
    span = {
        "type": "span",
        "name": "chat gpt-5.5",
        "startTime": [1782573865, 0],
        "endTime": [1782573866, 0],
        "attributes": [
            {"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}},
            {"key": "gen_ai.request.model", "value": {"stringValue": "gpt-5.5"}},
            {"key": "gen_ai.usage.input_tokens", "value": {"intValue": "1234"}},
            {"key": "gen_ai.usage.output_tokens", "value": {"intValue": "56"}},
            {"key": "gen_ai.usage.cache_read.input_tokens", "value": {"intValue": "1000"}},
            {"key": "github.copilot.nano_aiu", "value": {"intValue": "1500000000"}},
            {"key": "github.copilot.turn_id", "value": {"stringValue": "0"}},
        ],
    }
    calls = llm_calls_from_otel([span])
    assert len(calls) == 1
    c = calls[0]
    assert c.request_model == "gpt-5.5"
    assert c.input_tokens == 1234
    assert c.output_tokens == 56
    assert c.cache_read_input_tokens == 1000
    assert c.aiu == 1.5
    assert c.turn_id == "0"
