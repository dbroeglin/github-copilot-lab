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

    # real run (requires an authenticated `copilot` on PATH, and pytest available).
    # Uses a cheap model + low effort by default -- see DEFAULT_MODEL below.
    uv run copilot-experiments run   --root examples/tracer_bullet
    uv run copilot-experiments analyze --root examples/tracer_bullet --last
"""

from copilot_experiments import Experiment, Task, Variant

# --------------------------------------------------------------------------- #
# Cheap-by-default knobs for this smoke test.
#
# The whole point of this example is a *cheap, fast* way to confirm the harness
# works end-to-end against the real Copilot CLI. We therefore pin one of the
# cheapest models GitHub Copilot offers and a low reasoning effort, rather than
# inheriting your account default (which may be an expensive model at high
# effort). Change these two constants to run the smoke test on a different
# model / effort -- e.g. DEFAULT_MODEL = "claude-haiku-4.5", or set
# DEFAULT_MODEL = None to fall back to whatever model your CLI is configured to
# use.
#
# Cheapest widely-available Copilot models (per-token AI-credit cost, lowest
# first): "gpt-5-mini", "gpt-5.4-mini", "claude-haiku-4.5". See
# https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing
DEFAULT_MODEL: str | None = "gpt-5-mini"
DEFAULT_EFFORT: str | None = "low"

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
        # Minimum: a single variant pinned to a cheap model + low effort (see the
        # DEFAULT_MODEL / DEFAULT_EFFORT knobs above) so the smoke test stays cheap.
        Variant(
            name="default",
            model=DEFAULT_MODEL,
            reasoning_effort=DEFAULT_EFFORT,
            trials=1,
        ),
        # Add more cells to the matrix to compare models / efforts, e.g.:
        # Variant(name="opus-medium", model="claude-opus-4.7", reasoning_effort="medium"),
        # Variant(name="gpt-5", model="gpt-5.2"),
    ],
)
