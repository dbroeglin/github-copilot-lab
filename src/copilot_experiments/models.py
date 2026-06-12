"""Pydantic models: experiment definitions and result objects."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ._util import slugify

ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh", "max"]
Mode = Literal["interactive", "plan", "autopilot"]
ProviderType = Literal["openai", "azure", "anthropic"]
WireApi = Literal["completions", "responses"]


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


class Task(BaseModel):
    """What Copilot is asked to do, and how to provision/verify the workspace."""

    model_config = ConfigDict(extra="forbid")

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
        """Serializable representation with provider secrets redacted."""
        data = self.model_dump(exclude_none=True)
        if self.provider is not None:
            data["provider"] = self.provider.redacted()
        return data


class Experiment(BaseModel):
    """A named task plus the matrix of variants to run it under."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    task: Task
    variants: list[Variant]

    @property
    def slug(self) -> str:
        return slugify(self.name)


# --------------------------------------------------------------------------- #
# Result objects
# --------------------------------------------------------------------------- #
class Metrics(BaseModel):
    """Metrics parsed from a single trial's session ``events.jsonl``."""

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


class TrialResult(BaseModel):
    trial_no: int
    session_id: str
    exit_code: int
    duration_s: float
    success: bool | None = None
    metrics: Metrics = Field(default_factory=Metrics)


class VariantResult(BaseModel):
    variant: Variant
    trials: list[TrialResult] = Field(default_factory=list)

    @property
    def success_rate(self) -> float | None:
        graded = [t.success for t in self.trials if t.success is not None]
        if not graded:
            return None
        return sum(1 for s in graded if s) / len(graded)


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
