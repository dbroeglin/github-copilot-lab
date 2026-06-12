"""Shared pytest fixtures for the copilot-experiments test suite."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from copilot_experiments import Experiment, Task, Variant

FIXTURES = Path(__file__).parent / "fixtures"

# A portable verify command: succeeds only when a SOLVED marker exists.
_VERIFY = (
    f'"{sys.executable}" -c '
    '"import os,sys; sys.exit(0 if os.path.exists(\'SOLVED\') else 1)"'
)


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """A throwaway experiment-repo root with the sample fixture copied in."""
    fixtures = tmp_path / "fixtures" / "sample_task"
    fixtures.mkdir(parents=True)
    (fixtures / "seed.txt").write_text("seed\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def experiment() -> Experiment:
    return Experiment(
        name="Sample Experiment",
        description="A tiny experiment used by the test suite.",
        task=Task(
            prompt="Create a SOLVED file.",
            fixture="fixtures/sample_task",
            verify=_VERIFY,
        ),
        variants=[
            Variant(name="alpha", model="model-a"),
            Variant(name="beta", model="model-b", trials=2),
        ],
    )
