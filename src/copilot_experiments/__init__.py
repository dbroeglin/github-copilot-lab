"""copilot-experiments: a library + CLI for GitHub Copilot research experiments.

Public API
----------
Author Pier/Harbor task directories and run Pier jobs that include the real
GitHub Copilot CLI as an installed agent. The legacy Python experiment API is
still exported for migration and offline tests.

Pier configs can refer to the local Copilot agent import path exported as
``COPILOT_CLI_AGENT_IMPORT_PATH``.
"""

from __future__ import annotations

from .analysis import analyze_events, llm_calls_from_otel
from .deepswe import (
    DeepSweImportError,
    DeepSweImportResult,
    DeepSweSource,
    discover_deepswe_source,
    write_deepswe_job_config,
)
from .models import (
    DryRunCheck,
    DryRunReport,
    Experiment,
    ExperimentRun,
    LlmCallSummary,
    Metrics,
    ProviderConfig,
    SessionAnalysis,
    Task,
    TaskResult,
    ToolStat,
    TrialResult,
    TurnSummary,
    Variant,
    VariantResult,
)
from .pier_backend import COPILOT_CLI_AGENT_IMPORT_PATH, discover_pier_job_configs, run_pier_job
from .runner import dry_run_experiment, run_experiment

__all__ = [
    "DryRunCheck",
    "DryRunReport",
    "DeepSweImportError",
    "DeepSweImportResult",
    "DeepSweSource",
    "Experiment",
    "ExperimentRun",
    "LlmCallSummary",
    "Metrics",
    "ProviderConfig",
    "SessionAnalysis",
    "Task",
    "TaskResult",
    "ToolStat",
    "TrialResult",
    "TurnSummary",
    "Variant",
    "VariantResult",
    "COPILOT_CLI_AGENT_IMPORT_PATH",
    "analyze_events",
    "discover_deepswe_source",
    "discover_pier_job_configs",
    "dry_run_experiment",
    "llm_calls_from_otel",
    "run_pier_job",
    "run_experiment",
    "write_deepswe_job_config",
    "run",
]

# Convenient alias.
run = run_experiment

__version__ = "0.2.0"
