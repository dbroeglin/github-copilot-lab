"""Edge-case hardening tests for session analysis, derived from patterns observed in real local
Copilot sessions (compactions, stale prompt-cache misses, API timeouts, socket drops, aborts).

The fixtures below are **synthetic, anonymized, and simplified** -- they keep the *structure* of
the real ``events.jsonl`` payloads (event types, nesting, the fields the parser actually reads)
but carry invented IDs, no prose, and trimmed token counts. No real session is copied verbatim.

Where a number is load-bearing it is preserved: the stale-compaction ``costPerBatch`` rates and
token counts below price out to exactly the ``totalNanoAiu`` seen in the source session, so the
test exercises real rate-reconciliation math rather than a made-up total.
"""

from __future__ import annotations

from copilot_experiments import pricing
from copilot_experiments.analysis import analyze_events
from copilot_experiments.sessionlog import extract_economics

# --------------------------------------------------------------------------- #
# Builders modelled on real payload shapes
# --------------------------------------------------------------------------- #


def _assistant_turn(ts: str, *, out: int, inp: int, model: str = "claude-opus-4.8") -> list[dict]:
    return [
        {"type": "assistant.turn_start", "timestamp": f"{ts}.000Z", "data": {"turnId": "0"}},
        {
            "type": "assistant.message",
            "timestamp": f"{ts}.500Z",
            "data": {"model": model, "content": "working", "outputTokens": out, "inputTokens": inp},
        },
        {"type": "assistant.turn_end", "timestamp": f"{ts}.900Z", "data": {}},
    ]


def _stale_compaction(
    *, ts: str, pre_tokens: int, cache_write: int, output: int, nano: int, checkpoint: int = 1
) -> dict:
    """A compaction whose prompt cache had gone stale: ``cache_read`` is 0, the whole context is
    re-billed as fresh ``cache_write``. ``costPerBatch`` are the (non-default) live Opus rates.
    """
    return {
        "type": "session.compaction_complete",
        "timestamp": f"{ts}Z",
        "data": {
            "success": True,
            "preCompactionTokens": pre_tokens,
            "preCompactionMessagesLength": 90,
            "checkpointNumber": checkpoint,
            "compactionTokensUsed": {
                "inputTokens": 2,
                "outputTokens": output,
                "cacheReadTokens": 0,
                "cacheWriteTokens": cache_write,
                "copilotUsage": {
                    "tokenDetails": [
                        {
                            "batchSize": 1_000_000,
                            "costPerBatch": 500_000_000_000,
                            "tokenCount": 2,
                            "tokenType": "input",
                        },
                        {
                            "batchSize": 1_000_000,
                            "costPerBatch": 50_000_000_000,
                            "tokenCount": 0,
                            "tokenType": "cache_read",
                        },
                        {
                            "batchSize": 1_000_000,
                            "costPerBatch": 625_000_000_000,
                            "tokenCount": cache_write,
                            "tokenType": "cache_write",
                        },
                        {
                            "batchSize": 1_000_000,
                            "costPerBatch": 2_500_000_000_000,
                            "tokenCount": output,
                            "tokenType": "output",
                        },
                    ],
                    "totalNanoAiu": nano,
                },
                "duration": 43474,
                "model": "claude-opus-4.8",
            },
        },
    }


def _shutdown(
    *, ts: str, inp: int, cache_read: int, cache_write: int, output: int, nano: int, api_ms: int
) -> dict:
    return {
        "type": "session.shutdown",
        "timestamp": f"{ts}Z",
        "data": {
            "tokenDetails": {
                "input": {"tokenCount": inp},
                "cache_read": {"tokenCount": cache_read},
                "cache_write": {"tokenCount": cache_write},
                "output": {"tokenCount": output},
            },
            "totalNanoAiu": nano,
            "totalApiDurationMs": api_ms,
            "currentTokens": 12000,
        },
    }


def _error(ts: str, error_type: str, message: str) -> dict:
    return {
        "type": "session.error",
        "timestamp": f"{ts}Z",
        "data": {"errorType": error_type, "message": message, "stack": f"Error: {message}\n  at x"},
    }


def _abort(ts: str, reason: str = "user_initiated") -> dict:
    return {"type": "abort", "timestamp": f"{ts}Z", "data": {"reason": reason}}


# --------------------------------------------------------------------------- #
# Stale prompt-cache compaction: live (non-default) rates + cache miss
# --------------------------------------------------------------------------- #


def test_stale_compaction_exposes_nondefault_live_rates():
    comp = _stale_compaction(
        ts="2026-01-01T00:10:00",
        pre_tokens=152775,
        cache_write=217374,
        output=3176,
        nano=143_799_750_000,
    )
    rates = pricing.rates_from_compaction(comp["data"])
    # These differ from the documented defaults (input 300k, cache_write 375k, output 1.5M).
    assert rates == {
        "input": 500_000.0,
        "cache_read": 50_000.0,
        "cache_write": 625_000.0,
        "output": 2_500_000.0,
    }
    assert rates != pricing.default_rates()


def test_stale_compaction_session_uses_live_rates_for_decomposition():
    # A session that resumed after sitting idle: the compaction re-billed everything as cache_write
    # (cache_read 0), and the final shutdown likewise shows a cold cache (cache_read 0, fresh in).
    events = [
        {
            "type": "session.start",
            "timestamp": "2026-01-01T00:00:00Z",
            "data": {"sessionId": "s-stale", "selectedModel": "claude-opus-4.8"},
        },
        *_assistant_turn("2026-01-01T00:05:00", out=4000, inp=150000),
        _stale_compaction(
            ts="2026-01-01T00:10:00",
            pre_tokens=152775,
            cache_write=217374,
            output=3176,
            nano=143_799_750_000,
        ),
        _shutdown(
            ts="2026-01-01T00:15:00",
            inp=150000,
            cache_read=0,
            cache_write=150000,
            output=4000,
            # Price the shutdown with the same live Opus rates so AIU reconciles exactly.
            nano=150000 * 500_000 + 0 + 150000 * 625_000 + 4000 * 2_500_000,
            api_ms=42000,
        ),
    ]
    a = analyze_events(events)
    e = a.economics
    assert e.n_compactions == 1
    assert e.compaction_aiu == 143.79975
    # Cold cache: nothing was read from cache.
    assert e.cache_read_tokens == 0
    assert e.aiu_by_type["cache_read"] == 0.0
    # AIU split reconstructs to the authoritative total (within float rounding).
    assert round(sum(e.aiu_by_type.values()), 6) == e.aiu
    # Peak context comes from the pre-compaction size, not the (smaller) current tokens.
    assert e.peak_context_tokens == 152775


def test_aiu_split_differs_between_live_and_default_rates_on_cold_cache():
    # With a cold cache the entire cost lands on input + cache_write + output. Using the *live*
    # Opus rates the input/cache_write/output shares differ from what the defaults would yield,
    # which is exactly why reading live rates matters.
    counts = {"input": 150000, "cache_read": 0, "cache_write": 150000, "output": 4000}
    live = {
        "input": 500_000.0,
        "cache_read": 50_000.0,
        "cache_write": 625_000.0,
        "output": 2_500_000.0,
    }
    split_live = pricing.aiu_by_type(counts, live)
    split_default = pricing.aiu_by_type(counts, pricing.default_rates())
    assert split_live != split_default
    assert split_live["cache_read"] == 0.0 and split_default["cache_read"] == 0.0


# --------------------------------------------------------------------------- #
# Multiple compactions in one long session
# --------------------------------------------------------------------------- #


def test_multiple_compactions_accumulate_and_track_peak():
    events = [
        {"type": "session.start", "timestamp": "2026-01-01T00:00:00Z", "data": {}},
        _stale_compaction(
            ts="2026-01-01T01:00:00",
            pre_tokens=120000,
            cache_write=120000,
            output=2000,
            nano=80_000_000_000,
            checkpoint=1,
        ),
        _stale_compaction(
            ts="2026-01-01T02:00:00",
            pre_tokens=160000,
            cache_write=160000,
            output=2500,
            nano=100_000_000_000,
            checkpoint=2,
        ),
        _stale_compaction(
            ts="2026-01-01T03:00:00",
            pre_tokens=140000,
            cache_write=140000,
            output=2200,
            nano=90_000_000_000,
            checkpoint=3,
        ),
    ]
    e = extract_economics(events)
    assert e.n_compactions == 3
    # Peak is the largest pre-compaction context across all compactions.
    assert e.peak_context_tokens == 160000
    # Compaction AIU is the sum of all three compaction costs.
    assert e.compaction_aiu == pricing.to_aiu(80_000_000_000 + 100_000_000_000 + 90_000_000_000)
    # No shutdown -> no authoritative session totals.
    assert e.total_tokens is None


def test_compaction_start_and_complete_peak_interplay():
    events = [
        {
            "type": "session.compaction_start",
            "timestamp": "2026-01-01T01:00:00Z",
            "data": {
                "systemTokens": 11000,
                "conversationTokens": 99000,
                "toolDefinitionsTokens": 9000,
            },
        },
        _stale_compaction(
            ts="2026-01-01T01:00:05",
            pre_tokens=100000,
            cache_write=100000,
            output=2000,
            nano=70_000_000_000,
        ),
    ]
    e = extract_economics(events)
    # compaction_start sums to 119000, larger than the complete's preCompactionTokens (100000).
    assert e.peak_context_tokens == 119000


# --------------------------------------------------------------------------- #
# Transient API failures: timeout, socket drop, abort (no shutdown)
# --------------------------------------------------------------------------- #


_TIMEOUT_MSG = (
    "Execution failed: Error: Failed to get response from the AI model; retried 5 times "
    "(total retry wait time: 6.00 seconds) Last error: CAPIError: Failed native model HTTP "
    "request: error sending request: client error (Connect): operation timed out [ETIMEDOUT]"
)


def test_api_timeout_without_shutdown_degrades_gracefully():
    events = [
        {
            "type": "session.start",
            "timestamp": "2026-01-01T00:00:00Z",
            "data": {"sessionId": "s-timeout", "selectedModel": "claude-opus-4.8"},
        },
        *_assistant_turn("2026-01-01T00:01:00", out=120, inp=900),
        _error("2026-01-01T00:02:00", "query", _TIMEOUT_MSG),
    ]
    a = analyze_events(events)
    # No crash; the error is tallied in event_type_counts but does not fabricate economics.
    assert a.event_type_counts["session.error"] == 1
    assert a.economics.total_tokens is None
    # Per-message token counts are still recovered from assistant.message (saw_tokens path).
    assert a.output_tokens == 120
    assert a.input_tokens == 900


def test_socket_drop_then_abort_is_handled():
    events = [
        {"type": "session.start", "timestamp": "2026-01-01T00:00:00Z", "data": {}},
        *_assistant_turn("2026-01-01T00:01:00", out=50, inp=400),
        _error("2026-01-01T00:01:30", "system_und_err_socket", "SocketError: other side closed"),
        _abort("2026-01-01T00:01:31"),
    ]
    a = analyze_events(events)
    assert a.event_type_counts["session.error"] == 1
    assert a.event_type_counts["abort"] == 1
    assert a.economics.total_tokens is None
    # Timeline/turns still parse despite the abort.
    assert a.n_turns == 1


def test_failed_to_list_models_error_is_inert():
    events = [
        {"type": "session.start", "timestamp": "2026-01-01T00:00:00Z", "data": {}},
        _error("2026-01-01T00:00:01", "query", "Execution failed: Error: Failed to list models"),
    ]
    a = analyze_events(events)
    assert a.event_type_counts["session.error"] == 1
    assert a.n_turns == 0
    assert a.total_tokens is None


def test_timeout_error_does_not_override_authoritative_shutdown():
    # A transient timeout earlier in a session must not suppress the final shutdown's totals.
    events = [
        {"type": "session.start", "timestamp": "2026-01-01T00:00:00Z", "data": {}},
        _error("2026-01-01T00:00:30", "query", _TIMEOUT_MSG),
        *_assistant_turn("2026-01-01T00:01:00", out=200, inp=1000),
        _shutdown(
            ts="2026-01-01T00:02:00",
            inp=1000,
            cache_read=5000,
            cache_write=0,
            output=200,
            nano=1_000_000_000,
            api_ms=3000,
        ),
    ]
    a = analyze_events(events)
    assert a.event_type_counts["session.error"] == 1
    assert a.economics.total_tokens == 1000 + 5000 + 0 + 200
    assert a.economics.aiu == 1.0
