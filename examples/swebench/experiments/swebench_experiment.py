"""SWE-bench protocol example — runnable fully offline.

This reproduces the *shape* of the Bai et al. token-consumption protocol with Copilot
CLI as the agent, but uses two tiny **local fixtures** in place of real upstream repos
so the example runs with no network and no Docker:

  * ``textnorm`` — an easy one-function bug fix (difficulty ``easy``).
  * ``romans``   — a harder bug fix that needs the subtractive Roman forms
    (difficulty ``hard``).

Each task carries SWE-bench instance metadata (``instance_id``, ``difficulty``,
``FAIL_TO_PASS`` …) via :class:`SweBenchInstance`, so the run's summary shows the
**Difficulty vs cost** breakdown and the index/predictions-export paths behave exactly
as they do for real instances. ``verify`` is included here only so the offline example
produces a success signal without Docker; for *real* SWE-bench runs you omit ``verify``
and grade with ``copilot-experiments swebench-eval`` instead (see README).

Run it::

    # offline plumbing check (mock Copilot, no network, no Docker)
    uv run copilot-experiments run  --root examples/swebench --dry-run
    uv run copilot-experiments show --root examples/swebench --last

For the *real* protocol (download SWE-bench, run Copilot, grade in Docker) see the
README and the ``swebench-init`` / ``swebench-eval`` commands.
"""

from copilot_experiments import Experiment, Task, Variant
from copilot_experiments.models import SweBenchInstance

DEFAULT_MODEL: str | None = "gpt-5-mini"
DEFAULT_EFFORT: str | None = "low"

_NO_HINT = (
    "This project has a failing test suite caused by a bug. Fix the source code so that "
    "`python -m pytest -q` passes. Read the test file first to learn the exact expected "
    "behavior, then make the minimal change. Do not modify the tests."
)

experiment = Experiment(
    name="SWE-bench protocol (offline demo)",
    description=(
        "Two local-fixture 'instances' of differing difficulty, each repeated as trials "
        "(the paper's 'runs'), to demonstrate the SWE-bench protocol — difficulty-vs-cost "
        "and cross-run variance — without network or Docker."
    ),
    tasks=[
        Task(
            name="textnorm-easy",
            prompt=_NO_HINT,
            fixture="fixtures/textnorm",
            verify="python -m pytest -q",
            swebench=SweBenchInstance(
                instance_id="demo__textnorm-1",
                dataset="local-demo",
                repo="demo/textnorm",
                base_commit="0000000000000000000000000000000000000000",
                version="1.0",
                difficulty="easy",
                fail_to_pass=["test_textnorm.py::test_collapses_internal_runs"],
                pass_to_pass=["test_textnorm.py::test_strips_ends"],
            ),
        ),
        Task(
            name="romans-hard",
            prompt=_NO_HINT,
            fixture="fixtures/romans",
            verify="python -m pytest -q",
            swebench=SweBenchInstance(
                instance_id="demo__romans-1",
                dataset="local-demo",
                repo="demo/romans",
                base_commit="0000000000000000000000000000000000000000",
                version="1.0",
                difficulty="hard",
                fail_to_pass=["test_romans.py::test_subtractive_forms"],
                pass_to_pass=["test_romans.py::test_simple"],
            ),
        ),
    ],
    variants=[
        Variant(
            name="default",
            model=DEFAULT_MODEL,
            reasoning_effort=DEFAULT_EFFORT,
            trials=2,
        ),
    ],
)
