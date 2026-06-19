"""Pydantic models: experiment definitions and result objects."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ._util import slugify

ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh", "max"]
Mode = Literal["interactive", "plan", "autopilot"]
ProviderType = Literal["openai", "azure", "anthropic"]
WireApi = Literal["completions", "responses"]

# Outcome of a single trial, distinguishing *harness/infra* failures from the
# experiment's own (verify) result:
#   * ``ok``             -- Copilot ran to completion (verify pass/fail is separate).
#   * ``copilot_failed`` -- Copilot was invoked but errored out / produced no session
#                           log (e.g. authentication failure, bad working dir).
#   * ``harness_error``  -- the harness pipeline itself raised (provisioning, diffing).
TrialStatus = Literal["ok", "copilot_failed", "harness_error"]

# Roll-up of a run: every trial ``ok`` -> ``completed``; some but not all failed ->
# ``partial``; nothing ran successfully -> ``failed``.
RunStatus = Literal["completed", "partial", "failed"]

# Environment variable names whose *value* should be masked in stored artifacts.
# A safety net: BYOK secrets belong in ``ProviderConfig`` (already redacted), but a
# token set via the free-form ``Variant.env`` escape hatch must never be persisted.
_SECRET_ENV_HINT = re.compile(
    r"key|token|secret|password|passwd|bearer|credential|authorization", re.IGNORECASE
)


def _redact_env(env: dict[str, str]) -> dict[str, str]:
    """Mask values of environment variables whose name hints at a secret."""
    return {
        k: ("***redacted***" if _SECRET_ENV_HINT.search(k) else v) for k, v in env.items()
    }


# --------------------------------------------------------------------------- #
# Experiment definition
# --------------------------------------------------------------------------- #
class ProviderConfig(BaseModel):
    """Bring-Your-Own-Key custom model provider.

    Translated to ``COPILOT_PROVIDER_*`` environment variables when a variant
    using this provider is executed. Works with any OpenAI-compatible endpoint
    (Ollama, vLLM, Foundry Local), Azure OpenAI, or Anthropic.
    """

    model_config = ConfigDict(extra="forbid")

    base_url: str
    type: ProviderType = "openai"
    api_key: str | None = None
    bearer_token: str | None = None
    wire_api: WireApi | None = None
    model_id: str | None = None
    wire_model: str | None = None
    azure_api_version: str | None = None
    max_prompt_tokens: int | None = None
    max_output_tokens: int | None = None

    def to_env(self) -> dict[str, str]:
        """Render the provider config as Copilot CLI environment variables."""
        env: dict[str, str] = {
            "COPILOT_PROVIDER_BASE_URL": self.base_url,
            "COPILOT_PROVIDER_TYPE": self.type,
        }
        if self.api_key:
            env["COPILOT_PROVIDER_API_KEY"] = self.api_key
        if self.bearer_token:
            env["COPILOT_PROVIDER_BEARER_TOKEN"] = self.bearer_token
        if self.wire_api:
            env["COPILOT_PROVIDER_WIRE_API"] = self.wire_api
        if self.model_id:
            env["COPILOT_PROVIDER_MODEL_ID"] = self.model_id
        if self.wire_model:
            env["COPILOT_PROVIDER_WIRE_MODEL"] = self.wire_model
        if self.azure_api_version:
            env["COPILOT_PROVIDER_AZURE_API_VERSION"] = self.azure_api_version
        if self.max_prompt_tokens is not None:
            env["COPILOT_PROVIDER_MAX_PROMPT_TOKENS"] = str(self.max_prompt_tokens)
        if self.max_output_tokens is not None:
            env["COPILOT_PROVIDER_MAX_OUTPUT_TOKENS"] = str(self.max_output_tokens)
        return env

    def redacted(self) -> dict:
        """Serializable representation with secrets masked, for stored artifacts."""
        data = self.model_dump(exclude_none=True)
        for secret in ("api_key", "bearer_token"):
            if data.get(secret):
                data[secret] = "***redacted***"
        return data


class SweBenchInstance(BaseModel):
    """Per-instance SWE-bench metadata carried alongside a :class:`Task`.

    Lets the harness reproduce the protocol from Bai et al. ("How Do Coding Agents
    Spend Your Money?"): each task is one SWE-bench instance, the ``trials`` axis is
    the paper's repeated "runs", and grading is delegated to the official ``swebench``
    Docker harness. These fields are everything that stage needs to build a
    ``predictions.jsonl`` and map ground-truth ``resolved_ids`` back to trials. The
    test lists are stored for provenance/debugging; the official harness re-reads them
    from the dataset by ``instance_id`` at evaluation time.
    """

    model_config = ConfigDict(extra="forbid")

    instance_id: str
    """The canonical SWE-bench instance id (e.g. ``django__django-11099``)."""

    dataset: str = "princeton-nlp/SWE-bench_Verified"
    """HF dataset (or split) the instance came from; passed to the grader."""

    repo: str | None = None
    """``owner/name`` of the upstream repository."""

    base_commit: str | None = None
    """Commit the agent starts from (mirrors ``Task.ref``)."""

    environment_setup_commit: str | None = None
    """Commit whose environment the official harness builds the image from."""

    version: str | None = None
    """Repo version label SWE-bench uses to pick the right environment image."""

    difficulty: str | None = None
    """Human difficulty label (SWE-bench Verified), e.g. ``"<15 min fix"``."""

    fail_to_pass: list[str] = Field(default_factory=list)
    """Tests that must flip from failing to passing for the instance to be resolved."""

    pass_to_pass: list[str] = Field(default_factory=list)
    """Tests that must keep passing (regression guard)."""


class Task(BaseModel):
    """What Copilot is asked to do, and how to provision/verify the workspace."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    """Human-readable task name. When set, it seeds the task's directory slug;
    otherwise a positional ``task-NNN`` slug is assigned by the experiment."""

    prompt: str
    """The prompt handed to ``copilot -p``."""

    fixture: str | None = None
    """Path (relative to the experiment repo) to a directory copied as the
    starting workspace for every trial."""

    repo: str | None = None
    """Git URL to clone as the starting workspace (alternative to ``fixture``)."""

    ref: str | None = None
    """Branch, tag, or commit to check out when ``repo`` is used."""

    setup: list[str] = Field(default_factory=list)
    """Shell commands run in the workspace after provisioning, before Copilot."""

    verify: str | None = None
    """Shell command run in the workspace after Copilot finishes. Exit code 0
    means the trial succeeded. ``None`` means effectiveness is not measured."""

    swebench: SweBenchInstance | None = None
    """SWE-bench instance metadata. When set, the task is graded by the official
    ``swebench`` Docker harness (see :mod:`copilot_experiments.swebench`) rather than
    by ``verify``; the candidate patch is the trial's captured ``workspace.diff``."""


class Variant(BaseModel):
    """A single parameterization of an experiment (one cell of the matrix)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    model: str | None = None
    reasoning_effort: ReasoningEffort | None = None
    agent: str | None = None
    mode: Mode | None = None
    allow_tools: list[str] = Field(default_factory=list)
    deny_tools: list[str] = Field(default_factory=list)
    allow_all_tools: bool = True
    provider: ProviderConfig | None = None
    env: dict[str, str] = Field(default_factory=dict)
    extra_args: list[str] = Field(default_factory=list)
    trials: int = 1

    @property
    def slug(self) -> str:
        return slugify(self.name)

    def stored(self) -> dict:
        """Serializable representation with provider and env secrets redacted."""
        data = self.model_dump(exclude_none=True)
        if self.provider is not None:
            data["provider"] = self.provider.redacted()
        if self.env:
            data["env"] = _redact_env(self.env)
        return data


class Experiment(BaseModel):
    """A named task suite plus the matrix of variants to run it under.

    The comparison matrix is ``Tasks × Variants × Trials``. Provide either a
    single ``task`` (sugar for a one-task suite) or an explicit list of
    ``tasks`` -- exactly one of the two. See ADR-0012.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    task: Task | None = None
    tasks: list[Task] = Field(default_factory=list)
    variants: list[Variant]

    @model_validator(mode="after")
    def _check_task_suite(self) -> Experiment:
        if self.task is not None and self.tasks:
            raise ValueError("Provide either 'task' or 'tasks', not both.")
        if self.task is None and not self.tasks:
            raise ValueError("An experiment must define a 'task' or a non-empty 'tasks' list.")
        return self

    @property
    def slug(self) -> str:
        return slugify(self.name)

    def iter_tasks(self) -> list[tuple[str, Task]]:
        """Return the task suite as an ordered list of ``(task_slug, Task)``.

        Slugs come from ``Task.name`` when set, else a positional ``task-NNN``.
        Collisions are disambiguated with a numeric suffix so slugs are unique
        and stable for directory names and the index.
        """
        tasks = self.tasks if self.tasks else ([self.task] if self.task else [])
        result: list[tuple[str, Task]] = []
        seen: dict[str, int] = {}
        for idx, task in enumerate(tasks, start=1):
            base = slugify(task.name) if task.name else f"task-{idx:03d}"
            if base in seen:
                seen[base] += 1
                slug = f"{base}-{seen[base]}"
            else:
                seen[base] = 1
                slug = base
            result.append((slug, task))
        return result


# --------------------------------------------------------------------------- #
# Result objects
# --------------------------------------------------------------------------- #
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

    Flat scalars for aggregation and the SQLite index. The richer, nested view lives in
    :class:`TokenEconomics` on :class:`SessionAnalysis`; both are derived from the same events.
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


class PhaseStat(BaseModel):
    """Aggregated activity for one temporal phase of a session.

    The session's turns are split into five contiguous, near-equal groups
    (early -> later), echoing the phase-level analysis in Bai et al. (the paper's
    Finding #6: context construction dominates early phases, generation later
    ones). Only per-turn signals the Copilot log exposes reliably are aggregated:
    output tokens, tool activity, and duration. Per-phase *input*/cache/cost are
    intentionally omitted because Copilot reports those only as session totals
    (``session.shutdown``), never per turn -- see ``docs/analysis.md``.
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
    turns: list[TurnSummary] = Field(default_factory=list)
    phases: list[PhaseStat] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    event_type_counts: dict[str, int] = Field(default_factory=dict)


class TrialResult(BaseModel):
    trial_no: int
    session_id: str
    exit_code: int
    duration_s: float
    success: bool | None = None
    metrics: Metrics = Field(default_factory=Metrics)

    # Harness/infra outcome (orthogonal to ``success``, which is the experiment's
    # verify result). ``error`` is a short human-readable message; ``error_artifact``
    # names the file inside the trial directory to inspect for the full story.
    status: TrialStatus = "ok"
    error: str | None = None
    error_artifact: str | None = None

    @property
    def failed(self) -> bool:
        """True when the trial did not run cleanly (harness or copilot failure)."""
        return self.status != "ok"


class TaskResult(BaseModel):
    """All trials of one task within a variant (one cell of the suite × matrix)."""

    task_slug: str
    task_name: str | None = None
    prompt: str | None = None
    instance_id: str | None = None
    """SWE-bench instance id when this task is a SWE-bench instance (else ``None``)."""
    difficulty: str | None = None
    """SWE-bench difficulty label, surfaced for the difficulty-vs-cost analysis."""
    trials: list[TrialResult] = Field(default_factory=list)

    @property
    def success_rate(self) -> float | None:
        """Mean trial success for this task (the variability-aware measure)."""
        graded = [t.success for t in self.trials if t.success is not None]
        if not graded:
            return None
        return sum(1 for s in graded if s) / len(graded)

    @property
    def n_failed(self) -> int:
        """Number of trials that did not run cleanly (harness/copilot failures)."""
        return sum(1 for t in self.trials if t.failed)

    @property
    def resolved(self) -> bool | None:
        """Resolved@k: did *any* trial of this task pass (best-of-k)?"""
        graded = [t.success for t in self.trials if t.success is not None]
        if not graded:
            return None
        return any(graded)


class VariantResult(BaseModel):
    variant: Variant
    tasks: list[TaskResult] = Field(default_factory=list)

    @property
    def all_trials(self) -> list[TrialResult]:
        """Every trial across every task, flattened (for cost/token aggregates)."""
        return [t for tr in self.tasks for t in tr.trials]

    @property
    def success_rate(self) -> float | None:
        """Mean trial success across all tasks and trials of this variant."""
        graded = [t.success for t in self.all_trials if t.success is not None]
        if not graded:
            return None
        return sum(1 for s in graded if s) / len(graded)

    @property
    def mean_resolved_rate(self) -> float | None:
        """Mean over tasks of each task's mean trial success."""
        rates = [tr.success_rate for tr in self.tasks if tr.success_rate is not None]
        if not rates:
            return None
        return sum(rates) / len(rates)

    @property
    def resolved_at_k_rate(self) -> float | None:
        """Fraction of tasks resolved on at least one trial (best-of-k)."""
        graded = [tr.resolved for tr in self.tasks if tr.resolved is not None]
        if not graded:
            return None
        return sum(1 for r in graded if r) / len(graded)


class ExperimentRun(BaseModel):
    run_id: str
    experiment_slug: str
    experiment_name: str
    experiment_description: str = ""
    started_at: str
    finished_at: str | None = None
    git_base: str | None = None
    status: str = "running"
    variants: list[VariantResult] = Field(default_factory=list)

    @property
    def all_trials(self) -> list[TrialResult]:
        return [t for vr in self.variants for t in vr.all_trials]

    @property
    def n_failed_trials(self) -> int:
        return sum(1 for t in self.all_trials if t.failed)

    def rollup_status(self) -> RunStatus:
        """Derive the run status from its trials' harness/copilot outcomes."""
        trials = self.all_trials
        if not trials:
            return "failed"
        failed = self.n_failed_trials
        if failed == 0:
            return "completed"
        if failed == len(trials):
            return "failed"
        return "partial"


# --------------------------------------------------------------------------- #
# Dry-run (ephemeral plumbing check)
# --------------------------------------------------------------------------- #
class DryRunCheck(BaseModel):
    """One validated stage of the run pipeline during a ``--dry-run``."""

    name: str
    ok: bool
    detail: str = ""


class DryRunReport(BaseModel):
    """Result of an ephemeral dry-run: did each pipeline stage do its job?

    A dry-run runs the whole pipeline (with the mock invoker) inside a throwaway
    directory, records these checks, then deletes everything. Nothing is
    persisted; only this report survives.
    """

    experiment: str
    checks: list[DryRunCheck] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)
