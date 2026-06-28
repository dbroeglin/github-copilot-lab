"""copilot-experiments: Pier-first evaluation harness for GitHub Copilot CLI agents."""

from __future__ import annotations

from .analysis import analyze_events, llm_calls_from_otel
from .deepswe import (
    DeepSweImportError,
    DeepSweImportResult,
    DeepSweSource,
    discover_deepswe_source,
    write_deepswe_job_config,
)
from .models import LlmCallSummary, Metrics, SessionAnalysis, ToolStat, TurnSummary
from .pier_backend import COPILOT_CLI_AGENT_IMPORT_PATH, discover_pier_job_configs, run_pier_job

__all__ = [
    "COPILOT_CLI_AGENT_IMPORT_PATH",
    "DeepSweImportError",
    "DeepSweImportResult",
    "DeepSweSource",
    "LlmCallSummary",
    "Metrics",
    "SessionAnalysis",
    "ToolStat",
    "TurnSummary",
    "analyze_events",
    "discover_deepswe_source",
    "discover_pier_job_configs",
    "llm_calls_from_otel",
    "run_pier_job",
    "write_deepswe_job_config",
]

__version__ = "0.2.0"
