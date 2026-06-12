"""Example experiment: ask Copilot to fix a failing test, across a model matrix.

Run it:

    uv run copilot-experiments run --dry-run     # mock, no credits
    uv run copilot-experiments run               # real Copilot CLI
"""

from copilot_experiments import Experiment, Task, Variant

experiment = Experiment(
    name="Fix the calculator bug",
    description=(
        "A unit test fails because `multiply` is implemented incorrectly. "
        "Measure how reliably different models fix it so the test suite passes."
    ),
    task=Task(
        prompt=(
            "The tests in this project are failing. Find and fix the bug in "
            "calculator.py so that `python -m pytest -q` passes. Do not modify the tests."
        ),
        fixture="fixtures/buggy_calculator",
        verify="python -m pytest -q",
    ),
    variants=[
        Variant(name="opus-medium", model="claude-opus-4.7", reasoning_effort="medium"),
        Variant(name="gpt-5", model="gpt-5.2"),
        # BYOK example — a local model served by Ollama (uncomment to use):
        # from copilot_experiments import ProviderConfig
        # Variant(
        #     name="ollama-qwen",
        #     model="qwen2.5-coder:7b",
        #     provider=ProviderConfig(base_url="http://localhost:11434/v1"),
        # ),
    ],
)
