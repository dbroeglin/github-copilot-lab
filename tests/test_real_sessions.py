"""Regression tests that exercise the session parser against **real** Copilot CLI logs.

Unlike the synthetic fixtures in ``test_sessionlog.py`` / ``test_economics.py``, these run the
parsing / economics / analysis pipeline over captured ``events.jsonl`` + ``copilot-otel.jsonl``
from genuine Copilot CLI runs (see ``fixtures/real_sessions/README.md``). The golden values were
cross-checked against the raw ``session.shutdown`` payload, and the cross-source invariants below
re-derive the AIU total from an *independent* part of each log (the OTel ``chat`` spans).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from copilot_experiments.analysis import analyze_events
from copilot_experiments.sessionlog import extract_economics, load_events, parse_metrics

FIXTURES = Path(__file__).parent / "fixtures" / "real_sessions"


@dataclass(frozen=True)
class Expected:
    """Golden values verified against the raw ``session.shutdown`` payload."""

    slug: str
    model: str
    n_turns: int
    n_assistant_messages: int
    n_tool_calls: int
    n_tool_failures: int
    tool_calls_by_name: dict[str, int]
    input_tokens_noncached: int
    cache_read_tokens: int
    cache_write_tokens: int
    output_tokens: int
    input_tokens_total: int
    total_tokens: int
    reasoning_tokens: int | None
    n_requests: int
    api_duration_ms: int
    system_tokens: int
    tool_definitions_tokens: int
    conversation_tokens: int
    context_tokens: int
    files_modified: int
    lines_added: int
    lines_removed: int
    aiu: float
    n_llm_calls: int


CASES = [
    Expected(
        slug="fix_bug_gpt55",
        model="gpt-5.5",
        n_turns=5,
        n_assistant_messages=5,
        n_tool_calls=7,
        n_tool_failures=0,
        tool_calls_by_name={"glob": 3, "bash": 2, "apply_patch": 1, "view": 1},
        input_tokens_noncached=6283,
        cache_read_tokens=80896,
        cache_write_tokens=0,
        output_tokens=494,
        input_tokens_total=87179,
        total_tokens=87673,
        reasoning_tokens=53,
        n_requests=5,
        api_duration_ms=15934,
        system_tokens=6624,
        tool_definitions_tokens=11783,
        conversation_tokens=909,
        context_tokens=19319,
        files_modified=1,
        lines_added=1,
        lines_removed=1,
        aiu=8.6683,
        n_llm_calls=5,
    ),
    Expected(
        slug="fix_bug_claude_opus",
        model="claude-opus-4.7",
        n_turns=5,
        n_assistant_messages=5,
        n_tool_calls=4,
        n_tool_failures=0,
        tool_calls_by_name={"bash": 2, "edit": 1, "view": 1},
        input_tokens_noncached=10,
        cache_read_tokens=117653,
        cache_write_tokens=29793,
        output_tokens=472,
        input_tokens_total=147456,
        total_tokens=147928,
        reasoning_tokens=6,
        n_requests=5,
        api_duration_ms=14679,
        system_tokens=6591,
        tool_definitions_tokens=14493,
        conversation_tokens=818,
        context_tokens=21906,
        files_modified=1,
        lines_added=1,
        lines_removed=1,
        aiu=25.688275,
        n_llm_calls=5,
    ),
    Expected(
        slug="fix_bug_mai_flash",
        model="mai-code-1-flash-picker",
        n_turns=5,
        n_assistant_messages=5,
        n_tool_calls=6,
        n_tool_failures=0,
        tool_calls_by_name={"bash": 3, "edit": 1, "glob": 1, "view": 1},
        input_tokens_noncached=16443,
        cache_read_tokens=64000,
        cache_write_tokens=0,
        output_tokens=634,
        input_tokens_total=80443,
        total_tokens=81077,
        reasoning_tokens=None,
        n_requests=5,
        api_duration_ms=11155,
        system_tokens=5150,
        tool_definitions_tokens=12113,
        conversation_tokens=889,
        context_tokens=18155,
        files_modified=1,
        lines_added=1,
        lines_removed=1,
        aiu=1.998525,
        n_llm_calls=5,
    ),
    Expected(
        slug="fix_bug_gemini_pro",
        model="gemini-3.1-pro-preview",
        n_turns=6,
        n_assistant_messages=6,
        n_tool_calls=5,
        n_tool_failures=0,
        tool_calls_by_name={"bash": 3, "edit": 1, "view": 1},
        input_tokens_noncached=22257,
        cache_read_tokens=84254,
        cache_write_tokens=0,
        output_tokens=201,
        input_tokens_total=106511,
        total_tokens=106712,
        reasoning_tokens=289,
        n_requests=6,
        api_duration_ms=18677,
        system_tokens=5934,
        tool_definitions_tokens=12113,
        conversation_tokens=656,
        context_tokens=18706,
        files_modified=1,
        lines_added=1,
        lines_removed=1,
        aiu=6.37768,
        n_llm_calls=6,
    ),
]
IDS = [c.slug for c in CASES]


def _events(slug: str) -> list[dict]:
    return load_events(FIXTURES / slug / "events.jsonl")


def _otel(slug: str) -> list[dict]:
    return load_events(FIXTURES / slug / "copilot-otel.jsonl")


@pytest.mark.parametrize("exp", CASES, ids=IDS)
def test_parse_metrics_matches_real_session(exp: Expected) -> None:
    m = parse_metrics(_events(exp.slug))
    assert m.models == [exp.model]
    assert m.n_turns == exp.n_turns
    assert m.n_assistant_messages == exp.n_assistant_messages
    assert m.n_tool_calls == exp.n_tool_calls
    assert m.n_tool_failures == exp.n_tool_failures
    assert m.input_tokens == exp.input_tokens_total
    assert m.output_tokens == exp.output_tokens
    assert m.total_tokens == exp.total_tokens
    assert m.cache_read_tokens == exp.cache_read_tokens
    assert m.cache_write_tokens == exp.cache_write_tokens
    assert m.reasoning_tokens == exp.reasoning_tokens
    assert m.n_requests == exp.n_requests
    assert m.aiu == exp.aiu
    assert m.files_modified == exp.files_modified
    assert m.lines_added == exp.lines_added
    assert m.lines_removed == exp.lines_removed
    assert m.duration_s is not None and m.duration_s > 0


@pytest.mark.parametrize("exp", CASES, ids=IDS)
def test_extract_economics_matches_real_session(exp: Expected) -> None:
    e = extract_economics(_events(exp.slug))
    assert e.input_tokens_noncached == exp.input_tokens_noncached
    assert e.cache_read_tokens == exp.cache_read_tokens
    assert e.cache_write_tokens == exp.cache_write_tokens
    assert e.output_tokens == exp.output_tokens
    assert e.input_tokens_total == exp.input_tokens_total
    assert e.total_tokens == exp.total_tokens
    assert e.reasoning_tokens == exp.reasoning_tokens
    assert e.aiu == exp.aiu
    assert e.n_requests == exp.n_requests
    assert e.api_duration_ms == exp.api_duration_ms
    assert e.system_tokens == exp.system_tokens
    assert e.tool_definitions_tokens == exp.tool_definitions_tokens
    assert e.conversation_tokens == exp.conversation_tokens
    assert e.context_tokens == exp.context_tokens
    assert e.files_modified == exp.files_modified
    assert e.lines_added == exp.lines_added
    assert e.lines_removed == exp.lines_removed


@pytest.mark.parametrize("exp", CASES, ids=IDS)
def test_token_split_components_sum_to_total(exp: Expected) -> None:
    e = extract_economics(_events(exp.slug))
    assert (
        e.input_tokens_noncached + e.cache_read_tokens + e.cache_write_tokens
        == e.input_tokens_total
    )
    assert e.input_tokens_total + e.output_tokens == e.total_tokens


@pytest.mark.parametrize("exp", CASES, ids=IDS)
def test_aiu_by_type_reconciles_with_total(exp: Expected) -> None:
    e = extract_economics(_events(exp.slug))
    # Each per-type AIU is independently rounded, so the sum may differ from the authoritative
    # total by a rounding ULP; require reconciliation only to within that tolerance.
    assert e.aiu is not None
    assert abs(sum(e.aiu_by_type.values()) - e.aiu) <= 1e-6


@pytest.mark.parametrize("exp", CASES, ids=IDS)
def test_per_model_aiu_sums_to_session_total(exp: Expected) -> None:
    e = extract_economics(_events(exp.slug))
    assert len(e.model_metrics) == 1
    assert e.model_metrics[0].model == exp.model
    assert e.model_metrics[0].requests == exp.n_requests
    assert round(sum(m.aiu or 0.0 for m in e.model_metrics), 6) == e.aiu


@pytest.mark.parametrize("exp", CASES, ids=IDS)
def test_analysis_tool_counts_match_real_session(exp: Expected) -> None:
    a = analyze_events(_events(exp.slug), _otel(exp.slug))
    by_name = {t.name: t for t in a.tools}
    assert {n: t.calls for n, t in by_name.items()} == exp.tool_calls_by_name
    assert sum(t.failures for t in a.tools) == exp.n_tool_failures
    assert a.total_tokens == exp.total_tokens
    assert a.economics.aiu == exp.aiu


@pytest.mark.parametrize("exp", CASES, ids=IDS)
def test_otel_call_aiu_reconciles_with_shutdown(exp: Expected) -> None:
    """The strongest cross-check: an independent source (per-request OTel ``chat`` spans)
    must reproduce the ``session.shutdown`` AIU total to 4 decimals."""
    a = analyze_events(_events(exp.slug), _otel(exp.slug))
    assert len(a.llm_calls) == exp.n_llm_calls
    otel_aiu = sum(c.aiu or 0.0 for c in a.llm_calls)
    assert round(otel_aiu, 4) == round(a.economics.aiu, 4)


@pytest.mark.parametrize("exp", CASES, ids=IDS)
def test_otel_per_call_cache_tokens_reconcile_with_shutdown(exp: Expected) -> None:
    """Per-call cache read/write parsed from OTel ``chat`` spans (dotted
    ``gen_ai.usage.cache_read.input_tokens`` keys) must sum to the shutdown cache totals."""
    a = analyze_events(_events(exp.slug), _otel(exp.slug))
    cache_read = sum(c.cache_read_input_tokens or 0 for c in a.llm_calls)
    cache_write = sum(c.cache_creation_input_tokens or 0 for c in a.llm_calls)
    assert cache_read == exp.cache_read_tokens
    assert cache_write == exp.cache_write_tokens
