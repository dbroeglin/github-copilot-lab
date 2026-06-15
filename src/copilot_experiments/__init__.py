"""copilot-experiments: a library + CLI for GitHub Copilot research experiments.

Public API
----------
Define experiments in Python and run them across a parameter matrix (models,
reasoning efforts, agents, or BYOK providers), then collect and analyze the
resulting Copilot CLI session logs.

Example
-------
>>> from copilot_experiments import Experiment, Variant, Task
>>> exp = Experiment(
...     name="Fix the bug",
...     task=Task(prompt="Fix the failing test", fixture="fixtures/buggy_calculator",
...               verify="python -m pytest -q"),
...     variants=[
...         Variant(name="opus", model="claude-opus-4.7"),
...         Variant(name="gpt", model="gpt-5.2"),
...     ],
... )
"""

from __future__ import annotations

from .analysis import analyze_events
from .models import (
    DryRunCheck,
    DryRunReport,
    Experiment,
    ExperimentRun,
    Metrics,
    ProviderConfig,
    SessionAnalysis,
    Task,
    ToolStat,
    TrialResult,
    TurnSummary,
    Variant,
    VariantResult,
)
from .runner import dry_run_experiment, run_experiment

__all__ = [
    "DryRunCheck",
    "DryRunReport",
    "Experiment",
    "ExperimentRun",
    "Metrics",
    "ProviderConfig",
    "SessionAnalysis",
    "Task",
    "ToolStat",
    "TrialResult",
    "TurnSummary",
    "Variant",
    "VariantResult",
    "analyze_events",
    "dry_run_experiment",
    "run_experiment",
    "run",
]

# Convenient alias.
run = run_experiment

__version__ = "0.1.0"
