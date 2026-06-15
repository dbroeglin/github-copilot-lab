"""Tracer-bullet experiment: a small, multi-turn coding task.

This is the thin end-to-end slice that exercises every layer of the harness:
provision a workspace -> drive Copilot CLI -> capture the session log -> parse
metrics -> run analysis -> render in the CLI.

The task deliberately needs *several* assistant turns: the model has to read the
tests, implement three functions, run the suite, and fix anything that fails.

Run it:

    # dry-run (mock Copilot, no credits, synthetic multi-turn session log)
    uv run copilot-experiments run   --root examples/tracer_bullet --dry-run
    uv run copilot-experiments analyze --root examples/tracer_bullet --last

    # real run (requires an authenticated `copilot` on PATH, and pytest available)
    uv run copilot-experiments run   --root examples/tracer_bullet
    uv run copilot-experiments analyze --root examples/tracer_bullet --last
"""

from copilot_experiments import Experiment, Task, Variant

experiment = Experiment(
    name="Tracer bullet: textstats",
    description=(
        "Implement three text-statistics functions so a small pytest suite passes. "
        "A multi-turn task used to validate the end-to-end experiment + session-log "
        "analysis pipeline."
    ),
    task=Task(
        prompt=(
            "This project has failing tests. Implement the three functions in "
            "textstats.py so that `python -m pytest -q` passes. First read "
            "test_textstats.py to learn the exact expected behavior, then implement "
            "each function, then run the tests and fix anything that fails. Do not "
            "modify the tests."
        ),
        fixture="fixtures/textstats",
        verify="python -m pytest -q",
    ),
    variants=[
        # Minimum: a single variant using Copilot's default model.
        Variant(name="default", trials=1),
        # Add more cells to the matrix to compare models / efforts, e.g.:
        # Variant(name="opus-medium", model="claude-opus-4.7", reasoning_effort="medium"),
        # Variant(name="gpt-5", model="gpt-5.2"),
    ],
)
