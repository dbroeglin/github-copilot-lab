"""Task-suite example: two tasks of different difficulty through one variant matrix.

This demonstrates the *task axis* (ADR-0012): an experiment is `Tasks x Variants x
Trials`. Here a single cheap variant runs two independent tasks:

  1. ``reverse_words`` -- a trivial one-function warm-up.
  2. ``parse_csv``     -- a harder RFC 4180-style parser that needs a small state machine.

Because the tasks differ in difficulty, the run's summary shows the suite-coverage
metrics that only make sense across multiple tasks:

  * mean-success -- the mean over tasks of each task's mean trial success.
  * resolved@k   -- the fraction of tasks that *any* trial solved.

Run it:

    # dry-run (mock Copilot, no credits) -- creates a tasks/<slug>/ dir per task
    uv run copilot-experiments run     --root examples/task_suite --dry-run
    uv run copilot-experiments show    --root examples/task_suite --last

    # real run (needs an authenticated `copilot` on PATH and pytest available)
    uv run copilot-experiments run     --root examples/task_suite
    uv run copilot-experiments inspect --root examples/task_suite --last
"""

from copilot_experiments import Experiment, Task, Variant

# Cheap-by-default knobs, mirroring the tracer-bullet example: pin a cheap model at low
# effort so the suite stays inexpensive. Set DEFAULT_MODEL = None to inherit your CLI's
# configured model. See examples/tracer_bullet for more on these constants.
DEFAULT_MODEL: str | None = "gpt-5-mini"
DEFAULT_EFFORT: str | None = "low"

experiment = Experiment(
    name="Task suite: strtools + csvtools",
    description=(
        "Two independent tasks of increasing difficulty run through the same variant "
        "matrix to exercise the task axis and its suite-coverage metrics (mean-success "
        "and resolved@k)."
    ),
    tasks=[
        # Easy: one obvious function. Most models should solve this in a turn or two.
        Task(
            name="Reverse words",
            prompt=(
                "This project has a failing test. Implement the single function in "
                "strtools.py so that `python -m pytest -q` passes. Read "
                "test_strtools.py first to learn the exact expected behavior. Do not "
                "modify the tests."
            ),
            fixture="fixtures/strtools",
            verify="python -m pytest -q",
        ),
        # Harder: a quoting-aware CSV parser. Needs a character-by-character state machine
        # to get embedded commas, escaped quotes, and quoted newlines right -- several
        # assistant turns, and a task some cheap models will fail (which is the point:
        # resolved@k then drops below 1.0).
        Task(
            name="CSV parser",
            prompt=(
                "This project has failing tests. Implement `parse_csv` in csvtools.py so "
                "that `python -m pytest -q` passes. The tests in test_csvtools.py are the "
                "exact spec, including quoting, escaped quotes, embedded commas/newlines, "
                "and CRLF handling -- read them carefully first. Do not modify the tests."
            ),
            fixture="fixtures/csvtools",
            verify="python -m pytest -q",
        ),
    ],
    variants=[
        # One cheap variant is enough to demonstrate the suite. Add more cells (models /
        # efforts) to compare how each handles the easy vs. hard task, e.g.:
        # Variant(name="opus-medium", model="claude-opus-4.7", reasoning_effort="medium"),
        Variant(
            name="default",
            model=DEFAULT_MODEL,
            reasoning_effort=DEFAULT_EFFORT,
            trials=1,
        ),
    ],
)
