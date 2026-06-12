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

from .models import (
    Experiment,
    ExperimentRun,
    Metrics,
    ProviderConfig,
    Task,
    TrialResult,
    Variant,
    VariantResult,
)
from .runner import run_experiment

__all__ = [
    "Experiment",
    "ExperimentRun",
    "Metrics",
    "ProviderConfig",
    "Task",
    "TrialResult",
    "Variant",
    "VariantResult",
    "run_experiment",
    "run",
]

# Convenient alias.
run = run_experiment

__version__ = "0.1.0"
