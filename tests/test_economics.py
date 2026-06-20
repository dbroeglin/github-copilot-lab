"""Tests for token-economics extraction, AIU pricing, aggregation, and rendering.

Everything here is offline: synthetic ``session.shutdown`` / ``session.compaction_complete`` /
``session.truncation`` fixtures stand in for what the real Copilot CLI writes to ``events.jsonl``.
"""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from copilot_experiments import pricing
from copilot_experiments.analysis import analyze_events
from copilot_experiments.models import (
    Metrics,
    TaskResult,
    TrialResult,
    Variant,
    VariantResult,
)
from copilot_experiments.render import render_session_analysis
from copilot_experiments.report import aggregate_variant, build_summary, summary_markdown
from copilot_experiments.sessionlog import extract_economics, parse_metrics

# Token counts chosen so the default rates price out to a round 1.215 AIU.
_INPUT, _CACHE_READ, _CACHE_WRITE, _OUTPUT = 1000, 8000, 1200, 150
_NANO = 1_215_000_000  # = sum(count * default_rate) for the four types above.


def _compaction_event() -> dict:
    return {
        "type": "session.compaction_complete",
        "timestamp": "2026-01-01T00:00:05.000Z",
        "data": {
            "preCompactionTokens": 90_000,
            "compactionTokensUsed": {
                "copilotUsage": {
                    "totalNanoAiu": 2_000_000,
                    "tokenDetails": [
                        {
                            "tokenType": t,
                            "tokenCount": 10,
                            "batchSize": 1_000_000,
                            "costPerBatch": pricing.DEFAULT_COST_PER_BATCH[t],
                        }
                        for t in pricing.TOKEN_TYPES
                    ],
                }
            },
        },
    }


def _shutdown_event(**overrides: object) -> dict:
    data = {
        "tokenDetails": {
            "input": {"tokenCount": _INPUT},
            "cache_read": {"tokenCount": _CACHE_READ},
            "cache_write": {"tokenCount": _CACHE_WRITE},
            "output": {"tokenCount": _OUTPUT},
        },
        "totalNanoAiu": _NANO,
        "totalApiDurationMs": 4000,
        "modelMetrics": {
            "claude-opus-4.8": {
                "requests": {"count": 2},
                "usage": {
                    "inputTokens": _INPUT + _CACHE_READ + _CACHE_WRITE,
                    "outputTokens": _OUTPUT,
                    "cacheReadTokens": _CACHE_READ,
                    "cacheWriteTokens": _CACHE_WRITE,
                    "reasoningTokens": 40,
                },
                "totalNanoAiu": _NANO,
            }
        },
        "systemTokens": 5000,
        "conversationTokens": 3000,
        "toolDefinitionsTokens": 2000,
        "currentTokens": 10_000,
        "codeChanges": {"filesModified": ["a.py", "b.py"], "linesAdded": 3, "linesRemoved": 1},
    }
    data.update(overrides)
    return {"type": "session.shutdown", "timestamp": "2026-01-01T00:00:09.000Z", "data": data}


def _session(*, with_shutdown: bool = True) -> list[dict]:
    events = [
        {
            "type": "session.start",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "data": {"sessionId": "s1", "selectedModel": "claude-opus-4.8"},
        },
        {
            "type": "user.message",
            "timestamp": "2026-01-01T00:00:00.500Z",
            "data": {"content": "go"},
        },
        {
            "type": "assistant.turn_start",
            "timestamp": "2026-01-01T00:00:01.000Z",
            "data": {"turnId": "0"},
        },
        {
            "type": "assistant.message",
            "timestamp": "2026-01-01T00:00:01.200Z",
            "data": {
                "model": "claude-opus-4.8",
                "content": "reading",
                "outputTokens": 100,
                "toolRequests": [{"toolCallId": "c1", "name": "view"}],
            },
        },
        {
            "type": "tool.execution_start",
            "timestamp": "2026-01-01T00:00:01.300Z",
            "data": {"toolCallId": "c1", "toolName": "view"},
        },
        {
            "type": "tool.execution_complete",
            "timestamp": "2026-01-01T00:00:01.500Z",
            "data": {
                "toolCallId": "c1",
                "success": True,
                "toolTelemetry": {"metrics": {"durationMs": 120, "resultForLlmLength": 500}},
            },
        },
        {
            "type": "assistant.turn_end",
            "timestamp": "2026-01-01T00:00:02.000Z",
            "data": {"turnId": "0"},
        },
        {
            "type": "session.truncation",
            "timestamp": "2026-01-01T00:00:04.000Z",
            "data": {
                "preTruncationTokensInMessages": 120_000,
                "tokensRemovedDuringTruncation": 1500,
            },
        },
        _compaction_event(),
    ]
    if with_shutdown:
        events.append(_shutdown_event())
    return events


# --------------------------------------------------------------------------- #
# pricing
# --------------------------------------------------------------------------- #
def test_default_rates_are_per_token_nano():
    rates = pricing.default_rates()
    assert rates["input"] == 300_000.0
    assert rates["cache_read"] == 30_000.0
    assert rates["output"] == 1_500_000.0


def test_rates_from_compaction_reads_cost_per_batch():
    rates = pricing.rates_from_compaction(_compaction_event()["data"])
    assert rates == pricing.default_rates()


def test_rates_from_compaction_returns_none_when_absent():
    assert pricing.rates_from_compaction({}) is None


def test_aiu_by_type_splits_and_normalizes():
    counts = {
        "input": _INPUT,
        "cache_read": _CACHE_READ,
        "cache_write": _CACHE_WRITE,
        "output": _OUTPUT,
    }
    split = pricing.aiu_by_type(counts, normalize_to_nano=_NANO)
    assert split == {"input": 0.3, "cache_read": 0.24, "cache_write": 0.45, "output": 0.225}
    assert round(sum(split.values()), 6) == 1.215


def test_to_aiu_passthrough_none():
    assert pricing.to_aiu(None) is None
    assert pricing.to_aiu(1_500_000_000) == 1.5


# --------------------------------------------------------------------------- #
# extract_economics
# --------------------------------------------------------------------------- #
def test_economics_token_decomposition():
    e = extract_economics(_session())
    assert e.input_tokens_noncached == _INPUT
    assert e.cache_read_tokens == _CACHE_READ
    assert e.cache_write_tokens == _CACHE_WRITE
    assert e.output_tokens == _OUTPUT
    assert e.input_tokens_total == _INPUT + _CACHE_READ + _CACHE_WRITE
    assert e.total_tokens == _INPUT + _CACHE_READ + _CACHE_WRITE + _OUTPUT
    assert e.reasoning_tokens == 40


def test_economics_aiu_reconciles_with_split():
    e = extract_economics(_session())
    assert e.aiu == 1.215
    assert round(sum(e.aiu_by_type.values()), 6) == e.aiu


def test_economics_context_and_productivity():
    e = extract_economics(_session())
    assert e.system_tokens == 5000
    assert e.tool_definitions_tokens == 2000
    assert e.conversation_tokens == 3000
    assert e.context_tokens == 10_000
    assert e.files_modified == 2
    assert e.lines_added == 3
    assert e.lines_removed == 1
    assert e.n_requests == 2
    assert e.api_duration_ms == 4000


def test_economics_context_dynamics():
    e = extract_economics(_session())
    assert e.n_compactions == 1
    assert e.n_truncations == 1
    assert e.compaction_aiu == 0.002
    assert e.tokens_removed_truncation == 1500
    # Peak comes from the truncation's pre-truncation message size.
    assert e.peak_context_tokens == 120_000


def test_economics_per_model():
    e = extract_economics(_session())
    assert len(e.model_metrics) == 1
    m = e.model_metrics[0]
    assert m.model == "claude-opus-4.8"
    assert m.requests == 2
    assert m.aiu == 1.215


def test_economics_absent_without_shutdown():
    e = extract_economics(_session(with_shutdown=False))
    assert e.total_tokens is None
    assert e.aiu is None
    # Compaction/truncation still counted even with no shutdown.
    assert e.n_compactions == 1
    assert e.n_truncations == 1


def test_economics_sums_across_resumed_shutdowns():
    events = _session()
    events.append(_shutdown_event())  # a second shutdown (resume)
    e = extract_economics(events)
    assert e.output_tokens == 2 * _OUTPUT
    assert e.aiu == round(2 * 1.215, 6)
    assert e.n_requests == 4
    assert e.model_metrics[0].requests == 4


# --------------------------------------------------------------------------- #
# parse_metrics / analysis integration
# --------------------------------------------------------------------------- #
def test_parse_metrics_prefers_shutdown_totals():
    m = parse_metrics(_session())
    assert m.aiu == 1.215
    assert m.cache_read_tokens == _CACHE_READ
    assert m.total_tokens == _INPUT + _CACHE_READ + _CACHE_WRITE + _OUTPUT
    assert m.input_tokens == _INPUT + _CACHE_READ + _CACHE_WRITE
    assert m.output_tokens == _OUTPUT
    assert m.files_modified == 2
    assert m.peak_context_tokens == 120_000


def test_analysis_populates_economics_and_tool_telemetry():
    a = analyze_events(_session())
    assert a.economics.aiu == 1.215
    assert a.total_tokens == a.economics.total_tokens
    view = {t.name: t for t in a.tools}["view"]
    assert view.total_duration_ms == 120
    assert view.total_result_chars == 500


# --------------------------------------------------------------------------- #
# report aggregation
# --------------------------------------------------------------------------- #
def _variant_result(aius: list[float], successes: list[bool | None]) -> VariantResult:
    trials = [
        TrialResult(
            trial_no=i,
            session_id=f"s{i}",
            exit_code=0,
            duration_s=1.0,
            success=successes[i],
            metrics=Metrics(
                aiu=aius[i],
                total_tokens=int(aius[i] * 1000),
                lines_added=10,
                cache_read_tokens=8000,
            ),
        )
        for i in range(len(aius))
    ]
    task = TaskResult(task_slug="task-001", task_name=None, prompt="p", trials=trials)
    return VariantResult(variant=Variant(name="v", model="claude-opus-4.8"), tasks=[task])


def test_aggregate_variant_variance_and_cost():
    vr = _variant_result([1.0, 3.0], [True, False])
    agg = aggregate_variant(vr)
    assert agg["avg_aiu"] == 2.0
    assert agg["std_aiu"] == 1.414
    assert agg["cv_aiu"] == 0.707
    assert agg["total_aiu"] == 4.0
    # One solved task out of two -> all spend attributed to that single success.
    assert agg["aiu_per_solve"] == 4.0
    assert agg["avg_cache_read_tokens"] == 8000


def test_aggregate_variant_single_trial_zero_std():
    vr = _variant_result([2.5], [True])
    agg = aggregate_variant(vr)
    assert agg["std_aiu"] == 0.0
    assert agg["cv_aiu"] is None


def test_summary_markdown_has_cost_section():
    vr = _variant_result([1.0, 3.0], [True, True])

    class _Run:
        run_id = "r1"
        experiment_name = "Econ"
        experiment_slug = "econ"
        started_at = "2026-01-01T00:00:00Z"
        finished_at = "2026-01-01T00:10:00Z"
        status = "completed"
        variants = [vr]

    md = summary_markdown(build_summary(_Run()))
    assert "Cost & token economics" in md
    assert "AIU / solve" in md
    assert "Total cost:" in md


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def test_render_includes_economics_panel():
    a = analyze_events(_session())
    buf = StringIO()
    render_session_analysis(a, Console(file=buf, width=120, force_terminal=False))
    out = buf.getvalue()
    assert "Cost (AIU)" in out
    assert "Session economics" in out
    assert "cache_write" in out


def test_render_omits_economics_without_shutdown():
    a = analyze_events(_session(with_shutdown=False))
    buf = StringIO()
    render_session_analysis(a, Console(file=buf, width=120, force_terminal=False))
    out = buf.getvalue()
    assert "Cost (AIU)" not in out
