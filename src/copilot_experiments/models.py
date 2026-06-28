"""Pydantic models for Copilot session metrics and analysis."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModelMetric(BaseModel):
    """Per-model usage from ``session.shutdown.modelMetrics`` (multi-model sessions)."""

    model: str
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    aiu: float | None = None


class TokenEconomics(BaseModel):
    """Session-level token accounting and AIU cost.

    Parsed from ``session.shutdown`` (authoritative totals) plus ``session.compaction_*`` and
    ``session.truncation`` events. Every field is best-effort: a session that never emitted a
    ``session.shutdown`` (e.g. aborted) leaves the totals ``None``. Cost is expressed in **AIU**
    (GitHub's billing unit; ``totalNanoAiu / 1e9``). Premium requests are intentionally ignored
    (GitHub stopped using them on 2026-06-01).
    """

    # Token-type decomposition (the paper's taxonomy).
    input_tokens_noncached: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    input_tokens_total: int | None = None
    total_tokens: int | None = None

    # Cost (AIU).
    aiu: float | None = None
    aiu_by_type: dict[str, float] = Field(default_factory=dict)

    # Throughput.
    api_duration_ms: int | None = None
    n_requests: int | None = None

    # Context-window composition at end of session.
    system_tokens: int | None = None
    tool_definitions_tokens: int | None = None
    conversation_tokens: int | None = None
    context_tokens: int | None = None
    peak_context_tokens: int | None = None

    # Context-management dynamics.
    n_compactions: int = 0
    n_truncations: int = 0
    compaction_aiu: float | None = None
    tokens_removed_truncation: int | None = None

    # Productivity / effectiveness.
    files_modified: int | None = None
    lines_added: int | None = None
    lines_removed: int | None = None

    # Per-model split.
    model_metrics: list[ModelMetric] = Field(default_factory=list)


class Metrics(BaseModel):
    """Metrics parsed from a single trial's session ``events.jsonl``.

    Flat scalars for aggregation. The richer, nested view lives in :class:`TokenEconomics`
    on :class:`SessionAnalysis`; both are derived from the same events.
    """

    n_turns: int = 0
    n_assistant_messages: int = 0
    n_tool_calls: int = 0
    n_tool_failures: int = 0
    n_warnings: int = 0
    models: list[str] = Field(default_factory=list)
    duration_s: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    # Token-type decomposition and AIU cost (from session.shutdown; may be null).
    input_tokens_noncached: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None
    aiu: float | None = None
    aiu_by_type: dict[str, float] = Field(default_factory=dict)
    api_duration_ms: int | None = None
    n_requests: int | None = None

    # Context composition and dynamics.
    system_tokens: int | None = None
    tool_definitions_tokens: int | None = None
    conversation_tokens: int | None = None
    context_tokens: int | None = None
    peak_context_tokens: int | None = None
    n_compactions: int = 0
    n_truncations: int = 0
    compaction_aiu: float | None = None

    # Productivity (from session.shutdown.codeChanges).
    files_modified: int | None = None
    lines_added: int | None = None
    lines_removed: int | None = None


class ToolStat(BaseModel):
    """How often a single tool was invoked in a session, and how often it failed.

    ``total_duration_ms`` and ``total_result_chars`` aggregate ``toolTelemetry.metrics``
    (per-tool latency and the size of the result fed back to the model -- a proxy for the
    input-token cost each tool injects into subsequent requests).
    """

    name: str
    calls: int = 0
    failures: int = 0
    total_duration_ms: int = 0
    total_result_chars: int = 0


class LlmCallSummary(BaseModel):
    """One LLM request reconstructed from Copilot OTel ``chat <model>`` spans."""

    turn_id: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    duration_s: float | None = None
    request_model: str | None = None
    response_model: str | None = None
    response_id: str | None = None
    finish_reasons: list[str] = Field(default_factory=list)
    input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    aiu: float | None = None
    server_duration_ms: int | None = None
    current_tokens: int | None = None
    token_limit: int | None = None
    interaction_id: str | None = None
    service_request_id: str | None = None


class TurnSummary(BaseModel):
    """One assistant turn (``assistant.turn_start`` .. ``assistant.turn_end``)."""

    turn_no: int
    turn_id: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    duration_s: float | None = None
    assistant_messages: int = 0
    text_preview: str | None = None
    tools: list[str] = Field(default_factory=list)
    output_tokens: int | None = None
    input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    aiu: float | None = None
    api_duration_ms: int | None = None


class PhaseStat(BaseModel):
    """Aggregated activity for one temporal phase of a session.

    The session's turns are split into five contiguous, near-equal groups
    (early -> later), echoing the phase-level analysis in Bai et al. (the paper's
    Finding #6: context construction dominates early phases, generation later
    ones). Only native per-turn signals are aggregated: output tokens, tool
    activity, and duration. Per-phase *input*/cache/cost are intentionally
    omitted; OTel can provide per-call economics, but phase-level attribution is
    kept separate from native event analysis -- see ``docs/analysis.md``.
    """

    name: str
    turn_from: int
    turn_to: int
    n_turns: int = 0
    n_tool_calls: int = 0
    output_tokens: int = 0
    duration_s: float | None = None
    output_share: float | None = None


class SessionAnalysis(BaseModel):
    """A structured, human-friendly overview of a single Copilot session log.

    Derived purely from a session's ``events.jsonl``. Kept as plain data (no
    rendering) so it can be serialized to ``analysis.json``, rendered in the CLI
    with Rich, or consumed by a future web explorer.
    """

    # Session header / context.
    session_id: str | None = None
    copilot_version: str | None = None
    producer: str | None = None
    models: list[str] = Field(default_factory=list)
    reasoning_effort: str | None = None
    repository: str | None = None
    branch: str | None = None
    cwd: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_s: float | None = None

    # Totals.
    n_events: int = 0
    n_turns: int = 0
    n_user_messages: int = 0
    n_assistant_messages: int = 0
    n_tool_calls: int = 0
    n_tool_failures: int = 0
    n_warnings: int = 0
    n_hooks: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    # Token-type decomposition, AIU cost, context composition/dynamics, and productivity.
    economics: TokenEconomics = Field(default_factory=TokenEconomics)

    # Breakdowns.
    tools: list[ToolStat] = Field(default_factory=list)
    llm_calls: list[LlmCallSummary] = Field(default_factory=list)
    turns: list[TurnSummary] = Field(default_factory=list)
    phases: list[PhaseStat] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    event_type_counts: dict[str, int] = Field(default_factory=dict)
